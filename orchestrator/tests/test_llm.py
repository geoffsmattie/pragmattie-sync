import pytest

from sdlc.agents.llm import LLMError, StructuredLLM
from tests.fakes import (
    FakeAnthropic,
    answer,
    rate_limit_error,
    response,
    server_error,
    timeout_error,
)

SCHEMA = {"type": "object", "properties": {"adjustment": {"type": "integer"}}}


def call(fake, **kwargs):
    return StructuredLLM(client=fake).call(system="rules", user="the PR", schema=SCHEMA, **kwargs)


def test_the_request_has_the_shape_the_sonnet_5_api_accepts():
    fake = FakeAnthropic(response())
    call(fake)
    sent = fake.calls[0]
    assert sent["model"] == "claude-sonnet-5"
    # Sonnet 5 rejects sampling parameters with a 400, so none may ever be sent.
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(sent)
    assert sent["output_config"]["effort"] == "medium"
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    # The stable rules are cached; the PR-specific text is the (uncached) user turn.
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["messages"] == [{"role": "user", "content": "the PR"}]


def test_effort_none_omits_the_field_entirely_for_models_that_reject_it():
    # Haiku 4.5 returns a 400 ("This model does not support the effort parameter") if the field
    # is present at all, even as a no-op value — found live on the triage agent, 2026-09-23.
    fake = FakeAnthropic(response())
    call(fake, effort=None)
    assert "effort" not in fake.calls[0]["output_config"]
    assert fake.calls[0]["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}


def test_a_good_answer_comes_back_with_its_usage():
    result = call(FakeAnthropic(response(answer(adjustment=4), tokens=(1200, 150, 900, 100))))
    assert result.data["adjustment"] == 4
    assert (result.input_tokens, result.output_tokens) == (1200, 150)
    assert (result.cache_read_tokens, result.cache_write_tokens) == (900, 100)
    assert result.model == "claude-sonnet-5" and result.request_id == "req_test"
    assert result.latency_ms >= 0


def test_invalid_json_is_retried_once_then_fails_closed():
    fake = FakeAnthropic(response(text="not json"), response(answer(adjustment=2)))
    assert call(fake).data["adjustment"] == 2
    assert len(fake.calls) == 2

    fake = FakeAnthropic(response(text="not json"), response(text="[1, 2]"))
    with pytest.raises(LLMError) as caught:
        call(fake)
    assert caught.value.kind == "invalid_output" and len(fake.calls) == 2


def test_a_truncated_answer_is_invalid_output_not_a_loose_parse():
    fake = FakeAnthropic(response(text='{"adjustment": 3', stop_reason="max_tokens"))
    with pytest.raises(LLMError) as caught:
        call(fake)
    assert caught.value.kind == "invalid_output"


@pytest.mark.parametrize(
    ("outcome", "kind"),
    [
        (timeout_error(), "timeout"),
        (rate_limit_error(), "rate_limited"),
        (server_error(), "error"),
        (response(text="", stop_reason="refusal"), "refused"),
    ],
)
def test_every_failure_becomes_a_typed_error(outcome, kind):
    fake = FakeAnthropic(outcome)
    with pytest.raises(LLMError) as caught:
        call(fake)
    assert caught.value.kind == kind
    assert len(fake.calls) == 1  # the SDK retries transient errors itself; we don't double up


def test_a_missing_api_key_is_a_clear_error_not_a_crash():
    llm = StructuredLLM()  # no client injected and no key in the test environment
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        llm.call(system="s", user="u", schema=SCHEMA)
