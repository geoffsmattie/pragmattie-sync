# Orchestrator

The predictive SDLC layer. Empty in Phase 1; filled in from Phase 3.

| Folder | Phase | Purpose |
| --- | --- | --- |
| `signals/` | 3 | Pull GitHub events (issues, PRs, reviews, CI runs, deploys) into MySQL |
| `models/` | 4–5 | PR risk, delivery forecast, effort and test-failure models |
| `agents/` | 4–6 | Triage, PR risk reviewer, sprint forecaster, test selector, planner, release gate |
| `policies/` | 4 | Governance tiers (`tiers.yaml`): how much human approval each risk level needs |
