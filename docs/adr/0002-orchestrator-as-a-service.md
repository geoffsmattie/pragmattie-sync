# ADR 0002: The orchestrator is a separate service

- **Status:** Accepted
- **Date:** 2026-09-19

## Decision

The predictive SDLC layer lives in `orchestrator/` as its own Python service (FastAPI on
port 8001) with its own dependencies and its own Alembic migration history. It shares the
MySQL database with the CRM but only touches tables prefixed `sdlc_` and records its
migrations in `sdlc_alembic_version`.

## Why

- **It is the product we sell, not part of the CRM.** Keeping it separate shows clients it
  can sit beside *their* codebase with read access to their repository.
- **Independent change.** Agent and model work doesn't touch CRM code or migrations.
- **One database keeps local setup simple.** Each migration history filters to its own
  tables, so neither ever tries to drop the other's.

## Consequences

- Two API services run locally (8000 and 8001); the web app calls both.
- CI runs both migration histories against the same MySQL instance to prove they coexist.
