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
| `policies/` | 4 | Governance tiers (`tiers.yaml`): how much human approval each risk level needs |
| `policies/approvers.yaml` + `sdlc/approver.py` | 4 | Simulated second approver for tier T3, manual only, recorded as `simulated` in `sdlc_approvals` |

## Everyday commands

Run these with the stack up (`docker compose up`), from the repo root:

```bash
# Create the ~40-issue backlog in GitHub (dry run first, then for real)
docker compose exec orchestrator python -m sdlc.backlog
docker compose exec orchestrator python -m sdlc.backlog --apply

# Pull the latest issues, PRs, reviews and CI jobs from GitHub
docker compose exec orchestrator python -m sdlc.signals.github

# Regenerate the synthetic history (dates move forward to today)
docker compose exec orchestrator python -m sdlc.synth --reset

# Simulated second approver for tier T3 (manual only)
docker compose exec orchestrator python -m sdlc.approver pending           # what is waiting for you
docker compose exec orchestrator python -m sdlc.approver request 212 --tier T3
docker compose exec orchestrator python -m sdlc.approver approve 212       # add --source if ambiguous
```

The GitHub commands need `GITHUB_TOKEN` and `GITHUB_REPO` in your `.env` (see the root README).

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
