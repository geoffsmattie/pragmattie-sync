# Orchestrator

The predictive SDLC layer for PragMattie Sync. It runs as its own service (port 8001) so it
could be pointed at any team's repository: it only needs read access to the repo and a
database to keep what it learns.

| Path | Phase | What it does |
| --- | --- | --- |
| `sdlc/tables.py` | 3 | Signal tables (all prefixed `sdlc_`): engineers, sprints, issues, pull requests, CI runs, deployments, incidents |
| `sdlc/synth.py` | 3 | Generates ~6 months of synthetic engineering history with built-in patterns |
| `sdlc/signals/github.py` | 3 | Collects real issues, PRs, reviews and CI jobs from GitHub |
| `sdlc/backlog.py` + `backlog/backlog.yaml` | 3 | Creates the product backlog as labelled GitHub Issues |
| `sdlc/metrics.py`, `sdlc/api.py` | 3 | Delivery metrics (DORA, velocity, cycle time, CI health, risk by module) and their API |
| `sdlc/agents/` | 4-6 | Triage, PR risk, forecaster, planner, test selector, release gate |
| `policies/tiers.yaml` + `sdlc/tiers.py` | 4 | Governance tiers: score bands, floors, caps and what each tier requires; the loader validates it |
| `sdlc/changes.py` | 4 | Classifies the files a PR changed (tests, docs-only, migrations, modules) for the risk score |
| `sdlc/scoring.py` | 4 | Stage one of the risk score: ten weighted signals, point-in-time, capped at 100 |
| `sdlc/governance.py` | 4 | Score to tier: bands, floors (highest wins), the docs-only cap, and the fail-safe fallback |
| `sdlc/calibration.py` + `sdlc/risk.py` | 4 | `python -m sdlc.risk explain <pr>` and `calibrate`: read-only views of the score |
| `sdlc/audit.py` | 4 | Append-only audit trail (`sdlc_agent_decisions`), one row per agent run, either agent |
| `sdlc/agents/llm.py`, `pr_risk.py`, `gate.py`, `comment.py` | 4 | PR risk agent: score, the ±15 clamp, the tier from code, the `risk-gate` state, the PR comment |
| `sdlc/agents/github_effects.py` | 4 | Every write either agent makes to GitHub, in one place, gated by `ORCHESTRATOR_MODE` |
| `sdlc/modules.py`, `sdlc/similarity.py` | 4 | Module descriptions and word-overlap nearest-neighbour lookup, for the triage agent's prompt |
| `sdlc/agents/triage.py`, `triage_comment.py` | 4 | Triage agent: classification (Haiku 4.5), and the issue comment |
| `sdlc/runner.py` | 4 | Polls GitHub and drives both agents (`ORCHESTRATOR_MODE`: off, shadow or enforce) |
| `sdlc/issue_runner.py` | 4 | The triage agent's own poll loop, version-triggered on an issue's title+body, driven by `sdlc/runner.py` |
| `policies/approvers.yaml` + `sdlc/approver.py` | 4 | Simulated second approver for tier T3, manual only, recorded as `simulated` in `sdlc_approvals` |

## Everyday commands

Run these with the stack up (`docker compose up`), from the repo root:

```bash
# Create the ~40-issue backlog in GitHub (dry run first, then for real)
docker compose exec orchestrator python -m sdlc.backlog
docker compose exec orchestrator python -m sdlc.backlog --apply

# Pull the latest issues, PRs, reviews and CI jobs from GitHub
docker compose exec orchestrator python -m sdlc.signals.github

# Regenerate the synthetic history (dates move forward to today; also clears simulated approvals)
docker compose exec orchestrator python -m sdlc.synth --reset

# Score and tier a PR by hand, or grade the rubric against the history (read-only)
docker compose exec orchestrator python -m sdlc.risk explain 485
docker compose exec orchestrator python -m sdlc.risk calibrate
docker compose exec orchestrator python -m sdlc.risk calibrate --generated 30   # 30 histories, pooled

# The PR risk agent. Ships switched off; see ORCHESTRATOR_MODE in .env.
docker compose exec orchestrator python -m sdlc.runner dry-run 3       # exact request and cost ceiling; calls nothing
docker compose exec orchestrator python -m sdlc.runner try 3 --yes     # one real Claude call; writes nothing

# The triage agent, its own dry-run/try. Same ORCHESTRATOR_MODE, same off-by-default.
docker compose exec orchestrator python -m sdlc.issue_runner dry-run 12
docker compose exec orchestrator python -m sdlc.issue_runner try 12 --yes

# Start polling: sdlc.runner's run loop drives both agents together, one container, one schedule
docker compose --profile agents up -d

# Simulated second approver for tier T3 (manual only)
docker compose exec orchestrator python -m sdlc.approver pending           # what is waiting for you
docker compose exec orchestrator python -m sdlc.approver request 212 --tier T3
docker compose exec orchestrator python -m sdlc.approver approve 212       # add --source if ambiguous
```

The GitHub commands need `GITHUB_TOKEN` and `GITHUB_REPO` in your `.env` (see the root README).

## Watching shadow mode

With `ORCHESTRATOR_MODE=shadow`, open any pull request and within about 30 seconds the `agent`
service posts one comment naming the tier and its reasons, sets a `tier:Tn` label, and sets the
`risk-gate` commit status to **success** no matter what it found (shadow mode never blocks a
merge). The comment says what enforce mode would have done instead.

```bash
docker compose logs -f agent          # what the poller is doing right now
docker compose exec orchestrator python -m sdlc.approver pending   # any T3 needing the simulated approval
```

## Synthetic vs real data

Every signal row records its `source`: `synthetic` or `github`. The dashboard always says how
much of what it shows is simulated. On a client's repository the same code learns from their
real history instead.

Patterns built into the synthetic history, for the Phase 4-5 models to rediscover:

- Forecasting and Integrations work runs 1.5-2x over estimate.
- Large PRs, schema migrations and Billing & Auth changes cause most incidents.
- The integrations test suite is flaky (~7% of runs fail, then pass on re-run).
- Changes merged on Fridays cause more incidents.
- Velocity dips in holiday sprints and right after a release.
- Engineer profiles: Marcus ships big PRs with few defects; Dana ships small, steady PRs;
  Tomas (newer) has slower reviews and more rework.
