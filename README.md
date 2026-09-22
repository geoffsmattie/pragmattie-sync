# PragMattie Sync CRM

**Predictive orchestration of the SDLC with agentic AI: a working demo.**

PragMattie Sync is a fictional SaaS company that sells a CRM to mid-market B2B sales teams. This repo holds both its product and an AI-driven delivery system that predicts where software delivery will go wrong and has agents act before it does, with human approval scaled to risk.

> Demo built by **PragMattie Growth Partners, LLC**. PragMattie Sync, its team and its customers are fictional.

## Quick start

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Git.

```bash
# 1. Create your local environment file (first time only)
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env

# 2. Start everything
docker compose up --build
```

| What | Where |
| --- | --- |
| Web app | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| API health | http://localhost:8000/api/v1/health |
| Orchestrator API docs | http://localhost:8001/docs |
| MySQL | `localhost:3307` (user/password in `.env`) |

Stop with `Ctrl+C`, or `docker compose down` (add `-v` to wipe the database).

## Demo data

The first time the API starts on an empty database it loads a demo sales org: 6 reps, 60 accounts, 150 contacts, about 300 opportunities and 220 leads. Every company and person is invented, and emails use the reserved `.example` domain. Dates are relative to today, so the current quarter's forecast always looks live.

To reset the demo data while the app is running:

```bash
docker compose exec api python -m app.seed --reset
```

## Engineering history

The orchestrator also loads about six months of **synthetic** engineering history on first start: 13 sprints, ~330 issues, ~500 pull requests, ~3,600 CI runs, deployments and incidents. The **Engineering signals** page shows it as DORA measures, velocity, cycle time, CI health and risk by module, and always says how much is simulated versus collected from GitHub. The **Delivery board** page shows the same history (plus any real GitHub activity) as a live Kanban board — issues and PRs moving through triage, review, the risk gate, merge and deploy — with a Replay control to watch the last N days play out. See [orchestrator/README.md](orchestrator/README.md).

## Connecting GitHub

The backlog script and signals collector need a GitHub token in `.env`:

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Repository access: **Only select repositories** → `pragmattie-sync`.
3. Permissions: **Issues: Read and write**, **Pull requests: Read-only**, **Actions: Read-only** (Metadata is added automatically).
4. Put it in `.env` as `GITHUB_TOKEN=...` and set `GITHUB_REPO=<your-username>/pragmattie-sync`, then restart with `docker compose up -d`.

## What's in the CRM

| Screen | What it does |
| --- | --- |
| Home | Headline numbers: open leads, open deals, open pipeline, won this quarter |
| Leads | Search, filter and sort leads; create a lead; change status; convert to an account |
| Accounts | Browse companies with contact counts and open pipeline; drill into an account |
| Pipeline | Open deals by stage for this quarter, next quarter or all; move a deal between stages |
| Forecast | Quota, closed won, commit, best case and weighted forecast, by month, stage and rep |
| Engineering signals | DORA measures, sprint velocity, PR cycle time, CI health, risk and effort by module |
| Delivery board | Live Kanban view of issues and PRs moving through the pipeline, derived from the same tables — no stored status, filterable, with a history Replay |

API reference: http://localhost:8000/docs

## Repo layout

```
apps/api/          FastAPI backend (SQLAlchemy, Alembic, pytest)
apps/web/          Vue 3 front end (Vite, Vuetify, Pinia, Vitest)
orchestrator/      Predictive SDLC service (port 8001): signals, metrics, backlog, later agents
seed/              Demo CRM data and synthetic engineering history
docs/              Architecture and decision records (ADRs)
.github/workflows/ CI (and, later, agent workflows)
```

## Running tests without Docker

```bash
# API
cd apps/api
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest

# Orchestrator
cd orchestrator
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements-dev.txt
pytest

# Web
cd apps/web
npm install
npm test
```

## Roadmap

| Phase | Goal | Status |
| --- | --- | --- |
| 1 | Foundation: repo, Docker, CI | ✅ |
| 2 | The CRM: leads, accounts, pipeline, forecast | ✅ |
| 3 | Signals + synthetic history | ✅ |
| 4 | First agents: triage + PR risk, governance tiers | |
| 5 | Forecasting: delivery forecasts, planner agent | |
| 6 | Polish: test selector, release gate, audit log, client demo | |
