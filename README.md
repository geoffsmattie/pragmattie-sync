# SyncVista CRM

**Predictive orchestration of the SDLC with agentic AI: a working demo.**

SyncVista is a fictional SaaS company that sells a CRM to mid-market B2B sales teams. This repo holds both its product and an AI-driven delivery system that predicts where software delivery will go wrong and has agents act before it does, with human approval scaled to risk.

> Demo built by **PragMattie Growth Partners, LLC**. SyncVista, its team and its customers are fictional.

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
| MySQL | `localhost:3307` (user/password in `.env`) |

Stop with `Ctrl+C`, or `docker compose down` (add `-v` to wipe the database).

## Repo layout

```
apps/api/          FastAPI backend (SQLAlchemy, Alembic, pytest)
apps/web/          Vue 3 front end (Vite, Vuetify, Pinia, Vitest)
orchestrator/      Predictive SDLC layer: signals, models, agents, policies
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

# Web
cd apps/web
npm install
npm test
```

## Roadmap

| Phase | Goal | Status |
| --- | --- | --- |
| 1 | Foundation: repo, Docker, CI | ✅ |
| 2 | The CRM: leads, accounts, pipeline, forecast | |
| 3 | Signals + synthetic history | |
| 4 | First agents: triage + PR risk, governance tiers | |
| 5 | Forecasting: delivery forecasts, planner agent | |
| 6 | Polish: test selector, release gate, audit log, client demo | |
