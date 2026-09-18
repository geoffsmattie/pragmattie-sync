# ADR 0001: Tech stack

- **Status:** Accepted
- **Date:** 2026-09-18

## Decision

| Layer | Choice |
| --- | --- |
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic |
| Database | MySQL 8.4 (Docker locally) |
| Front end | Vue 3, Vite, Vuetify, Pinia, Vue Router |
| Tests | pytest, Vitest |
| CI | GitHub Actions |
| Agents (later) | Python + Claude API |

## Why

- Python across the API, models and agents keeps one language for the ML and AI work.
- MySQL is common in SaaS companies; SQLAlchemy keeps a move to Postgres to a config change.
- Vue 3 is quick to learn; Vuetify (MIT license) gives polished tables, forms and layout without custom design work. PrimeVue was considered, but version 5 moved to a license-key model.
