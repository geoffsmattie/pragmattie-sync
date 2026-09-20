# CLAUDE.md — PragMattie Sync

Guidance for Claude (and humans) working in this repo. Keep it current; when something
here is marked **TODO**, it has not been decided yet — ask Geoff rather than guessing.

## The project

- **PragMattie Sync** is a *fictional* SaaS company that sells **PragMattie Sync CRM**
  (leads, accounts & contacts, pipeline, forecasting) to mid-market B2B sales teams.
  The company, its team, customers and all seed data are invented.
- The real point of the repo is the **orchestration layer**: predictive orchestration of the
  SDLC with agentic AI (signals → predictions → agents → risk-based governance → dashboard).
- It is a **client demo and learning sandbox** for **PragMattie Growth Partners, LLC**
  (Geoff's consulting brand). The app footer credits PragMattie Growth Partners; the demo
  ends on its consulting-offer slide.
- **Local-only.** Demos run from Geoff's machine with Docker Compose. There is **no hosted
  deployment** and none should be added without asking. "Deployments" and "incidents" in the
  orchestrator are synthetic history, not real production events.
- The plan lives in the blueprint doc ("PragMattie Sync: Predictive SDLC Orchestration
  Blueprint"). Phases: 1 Foundation ✅ · 2 CRM ✅ · 3 Signals + synthetic history ✅ (on
  `phase-3-signals`) · 4 First agents (triage + PR risk, governance tiers) · 5 Forecasting ·
  6 Polish + client demo.

## Stack (settled — don't swap without asking)

| Layer | Choice | Notes |
| --- | --- | --- |
| CRM API | Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 | `apps/api` (port 8000); Python 3.12 in Docker |
| Orchestrator | Python, FastAPI, same libraries, httpx, PyYAML | `orchestrator/` — a **separate service** (port 8001), see `docs/adr/0002` |
| Database | **MySQL 8.4 — not Postgres** | Docker service `db`; host port **3307** (3306 is taken on Geoff's PC); containers use `db:3306` |
| Front end | **Vue 3 — not React** — Vite, **Vuetify** (MIT), Pinia, Vue Router, Chart.js via vue-chartjs | `apps/web` (port 5173). PrimeVue was rejected: v5 requires a license key |
| Tests / lint | pytest + ruff (Python), Vitest (web) | |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | |
| Agents (Phase 4+) | Python + Claude API | `ANTHROPIC_API_KEY` in `.env` locally, repo secret in GitHub |

Decisions are recorded as ADRs in `docs/adr/`.

## Naming conventions

- **Repo and folders:** `pragmattie-sync` (GitHub `geoffsmattie/pragmattie-sync`; local
  `C:\Users\geoff\Documents\GitHub\pragmattie-sync`).
- **Database, DB user and default password:** `pragmattie_sync` (underscore — MySQL identifiers).
- **Display name:** "PragMattie Sync" / "PragMattie Sync CRM". Consulting brand:
  "PragMattie Growth Partners, LLC".
- Web package: `pragmattie-sync-web`. Vuetify theme: `pragmattieSync` (colors from the
  PragMattie logo: navy `#2E3F55`, teal `#1B8A94`, gold `#E8B35A`).
- **Orchestrator tables are prefixed `sdlc_`** and its Alembic history uses the version table
  `sdlc_alembic_version`. The CRM's Alembic ignores `sdlc_*`; the orchestrator's only sees
  `sdlc_*`. Keep both `include_name` filters when touching `alembic/env.py`.
- Every orchestrator signal row has `source` = `synthetic` or `github`; the UI must always say
  how much of what it shows is simulated.
- Seed/demo emails and websites use the reserved **`.example`** domain. Never use real people
  or real company names in seed data.
- Migrations: `NNNN_short_name.py` with a matching `revision` id (e.g. `0002_crm_core`).
  On MySQL, downgrades drop tables rather than individual indexes (FK-backed indexes can't be
  dropped first).
- GitHub labels (created by `python -m sdlc.backlog`): `module:<name>`, `type:<feature|bug|chore>`,
  `priority:<p1|p2|p3>`, `points:<n>`, `epic:<name>`, and `caused-incident` on PRs.

## Running it

```bash
cp .env.example .env            # first time only (PowerShell: Copy-Item .env.example .env)
docker compose up --build       # web :5173, CRM API :8000, orchestrator :8001, MySQL :3307
docker compose up --build -V    # after dependency changes (renews the node_modules volume)
docker compose exec api python -m app.seed --reset             # reset CRM demo data
docker compose exec orchestrator python -m sdlc.synth --reset  # regenerate engineering history
```

Never commit `.env`. GitHub scripts need `GITHUB_TOKEN` (fine-grained, this repo only) and
`GITHUB_REPO` in `.env`.

## Test and lint commands (what CI runs)

```bash
# CRM API
cd apps/api
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest -q

# Orchestrator
cd orchestrator
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest -q

# Web
cd apps/web
npm ci
npm test && npm run build
```

- Python tests use a throwaway SQLite file; they need no MySQL or GitHub token.
- CI also runs both migration histories against a real MySQL 8.4 in one job
  (`alembic upgrade head` → seed/synth → `alembic check` → `alembic downgrade base`, for both).
- Ruff: line length 100, rules `E,F,I,B,UP`, target py312.
- Web formatter: **Prettier** (decided 2026-09-19). **TODO:** it isn't installed or configured yet —
  `apps/web` has no `prettier` dependency, config file or CI step. No web linter (e.g. ESLint)
  has been chosen.

## Branch and commit conventions

Settled:

- `main` is protected by a GitHub repository **ruleset** (Settings → Rules → Rulesets), not
  classic branch protection. It blocks deletion and force-pushes, and requires a **pull request**
  with green CI. Required checks, all defined in `.github/workflows/ci.yml`:
  **API (lint + tests)**, **Orchestrator (lint + tests)**, **API (migrations on MySQL)**,
  **Web (tests + build)**. (The ruleset lives in GitHub, not the repo; checked against GitHub's
  rules API on 2026-09-19.)
- **Required approvals on `main`: zero, for now** (Geoff is the only contributor). Revisit when
  Phase 4 enforces the governance tiers below, since T1–T3 need human approvals.
- **One branch per phase**, cut from an up-to-date `main`: `phase-<n>-<topic>`
  (e.g. `phase-2-crm`, `phase-3-signals`). Delete the branch after merge.
- **Non-phase work** (fixes and chores between phases): `non-phase-work-<topic>`
  (e.g. `non-phase-work-fix-lead-filter`), cut from an up-to-date `main`. Delete after merge.
- **Merge strategy: merge commit** (as PRs #1 and #2 did), not squash. This is a convention:
  the ruleset still allows squash and rebase merges too, so pick "Create a merge commit".
- **Commit format: Conventional Commits** — `type(scope): description`, e.g.
  `feat(api): add lead conversion endpoint`, `docs: add CLAUDE.md project guidance`. Adopted
  2026-09-19; earlier commits (`Phase 2: CRM screens and demo data`) keep their old style.
- Geoff pushes with **GitHub Desktop**. Claude may stage and commit when Geoff asks, but never
  unprompted, and does not push.
- **No attribution lines** (`Co-Authored-By`, `Claude-Session`, "Generated with…") in commit
  messages or PR descriptions.

Not yet decided:

- **TODO:** how Conventional Commits and the phase prefix fit together — whether the phase
  becomes a scope (e.g. `feat(phase-3): …`) or is dropped from commit messages.

## Governance tiers (from the blueprint)

Human oversight scales with predicted risk. Low-risk work flows without waiting; high-risk
work always gets a person. **Status: designed, not yet built — implementation is Phase 4.**

| Tier | When it applies | Approvals to merge | Tests | Deploy |
| --- | --- | --- | --- | --- |
| **T0: Auto** | Risk < 20, docs/copy/config only | AI review only | Selected suites | Automatic |
| **T1: Light** | Risk 20–49 | AI review + 1 human | Selected suites | Automatic after merge |
| **T2: Standard** | Risk 50–79, or touches Pipeline/Forecasting | AI review + 1 senior human | Full suite | Release gate checks |
| **T3: Critical** | Risk ≥ 80, or touches Billing/Auth, or schema migration | 2 humans incl. code owner | Full suite + manual QA | Human sign-off required |

- **Overrides:** a human can raise any PR's tier at any time; lowering a tier requires a
  written reason in the PR. Both go to the audit log.
- **Enforcement (planned):** the `main` ruleset will require a `risk-gate` status check.
  The PR risk agent sets it to pass only when the tier's approvals are present. Every agent
  decision is written to an audit table with its inputs, scores and the tier applied.
- Tiers will live in `orchestrator/policies/tiers.yaml` so they can be changed without code.
- Agents never merge, deploy or close issues beyond what their tier allows.
- **Highest tier wins** when several rows match (confirmed by Geoff, 2026-09-19): e.g. a
  low-risk PR with a schema migration is T3.
- **Approvers:** the "senior human" (T2) and the "code owner" (T3) are both **Geoff**
  (decided 2026-09-19). There is no `CODEOWNERS` file yet.
- **Deploy column:** a deploy-only gate that stays dormant (stubbed) in local runs and only
  fires if a real release pipeline is triggered on GitHub (decided 2026-09-19). No such pipeline
  exists — the project is local-only — so today the gate is always stubbed.

### Simulated second approver

T3 needs "2 humans incl. code owner", but Geoff is the only human, so a **simulated approver**
fills the second seat and keeps the process from locking (decided 2026-09-19).

- Declared in `orchestrator/policies/approvers.yaml`; covers **T3 only** (T2 needs one senior
  human, which is Geoff himself). Code: `orchestrator/sdlc/approver.py`; table `sdlc_approvals`.
- **Manual only.** It approves a PR only when Geoff runs `approve` for that PR. There is no
  auto-approve.
- Every approval is stored with `source = simulated`. The UI and audit log must always show it
  as simulated, never as a real human approval.

```bash
docker compose exec orchestrator python -m sdlc.approver pending                       # what's waiting on me
docker compose exec orchestrator python -m sdlc.approver request <pr> --tier T3 --reason "..."
docker compose exec orchestrator python -m sdlc.approver approve <pr>                  # add --source if the number is ambiguous
```

- **The reminder prompt:** when Geoff asks **"What approvals do I have awaiting for me?"** (or
  close to it), run the `pending` command above and report what it lists. If the stack isn't
  running, say so instead of guessing; if nothing is waiting, say that.
- **Claude never runs `approve`** unless Geoff names the PR in that same message, and runs
  `request` only when asked. Listing with `pending` is always fine.
- Until Phase 4 nothing computes a PR's tier, so `pending` stays empty until someone runs
  `request`. The PR risk agent should call `request_approval` when it assigns T3, and the
  `risk-gate` check should stay pending until the approval is recorded.

### Phase 4 decisions (2026-09-20)

The Phase 4 build spec lives in the blueprint doc, which is kept out of this public repo.
Decisions made while building it:

- **Polling, not webhooks.** The orchestrator polls GitHub (about every 30 seconds), because a
  local-only laptop can't receive webhooks.
- **Human sign-off is a tick-box in the risk agent's PR comment.** GitHub won't let a PR's author
  approve it, so don't turn on "require review from code owners" in the ruleset: with one human
  it would lock Geoff out. A `CODEOWNERS` file may still be added for documentation.
- **`risk-gate` is a commit status**, so the GitHub token needs "Commit statuses: read and
  write". Run in shadow mode first (`ORCHESTRATOR_MODE=off|shadow|enforce` in `.env`). Don't make
  `risk-gate` a required check until shadow has run a full sprint, and give the repo admin a
  ruleset bypass so a stopped local stack can't block every merge.
- **Models:** Haiku 4.5 for triage, Sonnet 5 for the ±15 risk adjustment, ids kept in `.env`.
  Every run records its tokens in the audit table. Geoff wants API usage and cost checked
  periodically: report it at each Phase 4 milestone.
- **"Docs or config only" (capped at T0) never includes** `orchestrator/policies/`,
  `.github/workflows/` or dependency manifests, so a PR that edits governance, CI or
  dependencies can't be capped at T0.
- PRs carry `test_files_changed`, `docs_only` and `modules_touched` (from `sdlc/changes.py`).
  An existing database needs `sdlc.synth --reset`, or a collector run, to fill them in.

Open items:

- **TODO:** the risk score (0–100): the stage-one rubric and Claude's ±15 adjustment are specified
  in the blueprint but not built yet. `tiers.yaml` and its loader (`sdlc/tiers.py`) exist, but
  until the score exists no PR has a real tier.
- **TODO:** what "selected suites" means (depends on the Phase 6 test-selector agent) and what
  the "manual QA" step for T3 consists of.
- **TODO:** the audit table `sdlc_agent_decisions` is designed in the blueprint (append-only, one
  row per agent run) but not built yet.
