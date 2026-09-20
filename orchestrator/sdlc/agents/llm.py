"""A thin, strict wrapper around one Claude call that must return JSON matching a schema.

What it enforces, so callers don't have to remember:
  - the answer is JSON that validates against the schema, or the call fails closed;
  - invalid output is retried once, then reported as `invalid_output` (never parsed loosely);
  - every failure becomes an LLMError with a `kind` the audit table records;
  - tokens, latency and the request id come back with the answer.

Sonnet 5 takes no `temperature`, `top_p` or `top_k` (they return a 400), so repeatability comes
from a fixed prompt, a JSON schema, medium effort and a bounded adjustment enforced in code.
"""

import json
import time
from dataclasses import dataclass

import anthropic

from sdlc.config import get_settings

RETRIES_ON_INVALID_OUTPUT = 1


class LLMError(Exception):
    """A failed call. `kind` is one of: timeout, rate_limited, refused, invalid_output, error."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class LLMResult:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    latency_ms: int
    request_id: str | None


class StructuredLLM:
    def __init__(self, client=None, model: str | None = None, max_tokens: int | None = None):
        settings = get_settings()
        self.model = model or settings.risk_model
        self.max_tokens = max_tokens or settings.risk_max_output_tokens
        self._client = client
        self._timeout = settings.agent_timeout_seconds
        self._api_key = settings.anthropic_api_key

    @property
    def client(self):
        if self._client is None:
            if not self._api_key:
                raise LLMError("error", "ANTHROPIC_API_KEY is not set.")
            # The SDK already retries connection errors, 408, 409, 429 and 5xx with backoff.
            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=self._timeout, max_retries=2
            )
        return self._client

    def request_kwargs(self, system: str, user: str, schema: dict, effort: str) -> dict:
        """The exact request, so a dry run can show it without sending it."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # The stable instructions go first and are cached; the PR-specific text comes last.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }

    def call(self, *, system: str, user: str, schema: dict, effort: str = "medium") -> LLMResult:
        kwargs = self.request_kwargs(system, user, schema, effort)
        last_problem = ""
        for _ in range(1 + RETRIES_ON_INVALID_OUTPUT):
            started = time.monotonic()
            try:
                response = self.client.messages.create(**kwargs)
            except anthropic.APITimeoutError as err:
                raise LLMError("timeout", f"The API call timed out: {err}") from err
            except anthropic.RateLimitError as err:
                raise LLMError("rate_limited", "The API rate limit was hit.") from err
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as err:
                raise LLMError("error", f"{type(err).__name__}: {err}") from err
            latency_ms = int((time.monotonic() - started) * 1000)

            if response.stop_reason == "refusal":
                raise LLMError("refused", "The model declined this request.")
            data, last_problem = _parse_json(response)
            if data is not None:
                usage = response.usage
                return LLMResult(
                    data=data,
                    model=response.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                    cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    latency_ms=latency_ms,
                    request_id=getattr(response, "_request_id", None),
                )
        raise LLMError("invalid_output", last_problem)


def _parse_json(response) -> tuple[dict | None, str]:
    if response.stop_reason == "max_tokens":
        return None, "The answer hit the output limit before the JSON was complete."
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None, "The answer had no text block."
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        return None, f"The answer was not valid JSON: {err}"
    if not isinstance(data, dict):
        return None, "The answer was JSON but not an object."
    return data, ""
