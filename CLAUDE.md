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
- The PR risk agent (`sdlc/runner.py`) calls `request_approval` when it assigns T3, so `pending`
  fills in by itself once the agent runs. In enforce mode the `risk-gate` check stays pending until
  the sign-off boxes are ticked and this approval is recorded.

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
  periodically: report it at each Phase 4 milestone. Sonnet 5 rejects `temperature`, `top_p` and
  `top_k` with a 400, so never send them; repeatability comes from a fixed prompt, a JSON schema,
  medium effort and the clamp enforced in code. The blueprint's "low temperature" can't apply.
- **"Docs or config only" (capped at T0) never includes** `orchestrator/policies/`,
  `.github/workflows/` or dependency manifests, so a PR that edits governance, CI or
  dependencies can't be capped at T0.
- PRs carry `test_files_changed`, `docs_only` and `modules_touched` (from `sdlc/changes.py`).
  An existing database needs `sdlc.synth --reset`, or a collector run, to fill them in.

Open items:

- **PR risk agent: built, live-tested, running in shadow.** Its first real call (2026-09-20, PR
  #3) and its first full shadow-mode run (2026-09-22, PR #5 — comment, `tier:T0` label and a
  passing `risk-gate` status all posted correctly) both worked. **TODO:** shadow mode needs a full
  sprint's worth of real PRs, and its results read, before `risk-gate` becomes a required check.
  - Pieces: `sdlc/agents/llm.py` (one strict Claude call), `pr_risk.py` (score, the ±15 clamp, the
    tier from code), `gate.py` (the `risk-gate` state), `comment.py` (the PR comment and its
    sign-off boxes), `github_effects.py` (the only writes: one comment, one `tier:` label, the
    status), and `sdlc/runner.py` (the poll loop, now shared with triage — see below).
  - `ORCHESTRATOR_MODE` ships as `off`, which does nothing at all; `dry-run <pr>` shows the exact
    request and a cost ceiling and calls nothing; `try <pr>` needs `--yes` to spend money, never
    writes to GitHub, and records one `trigger = trial` audit row so its tokens count in cost
    reports (added 2026-09-23). The poll loops and the delivery board ignore trial rows; the
    decision log shows them. Start polling with `docker compose --profile agents up -d`.
  - A new commit is assessed once and its sign-off boxes start empty. A failed run fails closed to
    the floor tier or T2 and is retried up to three times, five minutes apart.
  - The agent never merges, approves, closes or pushes, and the model can't name a tier.
- **Triage agent: built, tested, and live-verified against a 40-issue smoke test
  (2026-09-23).** Haiku 4.5, low effort (classification against a fixed vocabulary). The first
  live `run` against the real backlog surfaced two API-drift bugs, both fixed same-day: Claude's
  schema API rejects `minimum`/`maximum` on a `number` field (so `confidence` is clamped in code,
  not the schema), and Haiku 4.5 rejects the `effort` key in `output_config` entirely — `effort`
  is now `str | None` throughout `StructuredLLM`, omitted from the request when `None`. Both have
  regression tests. It now runs in the shared poll loop alongside the PR risk agent.
  - Pieces: `sdlc/modules.py` (module descriptions for the prompt), `sdlc/similarity.py`
    (deterministic word-overlap nearest-neighbour lookup — no embeddings), `sdlc/agents/triage.py`
    (classification: module/type/priority/points/duplicate_of/confidence/questions),
    `triage_comment.py` (the issue comment), and `sdlc/issue_runner.py` (its own poll loop,
    driven by `sdlc/runner.py`'s `run`/`once` alongside the PR risk agent — one container, one
    schedule, per the blueprint's shared `ORCHESTRATOR_MODE`).
  - **Trigger:** an issue is triaged once per distinct title+body ("version", a content hash —
    not the issue's `updated_at`, since the agent's own label/comment writes would otherwise bump
    that and make it re-trigger itself). Editing the title or body is a new version. A `retriage`
    label forces another run even on unchanged content, bypassing the automatic-failure backoff
    (that backoff exists only to stop the agent hammering the API on its own repeated failures,
    not to throttle a deliberate human action), and is removed once that run succeeds.
  - **Autonomy:** only ever replaces `module:`/`type:`/`priority:`/`points:` labels, add-only adds
    `needs-info` (low confidence or open questions) and `possible-duplicate` (only when the model
    names a candidate it was actually shown — a hallucinated issue number is dropped in code), and
    keeps one comment up to date. Never closes an issue, assigns it, or edits its text.
  - **Human overrides:** if a human has changed a dimension label since the agent's last
    successful run on that issue, later runs leave that dimension alone and record the difference
    on the new decision's `human_override` field, rather than fighting the correction.
  - **Delivery board: built and live-verified (2026-09-23).** The demo-facing Kanban view
  (`/board` in the web app) that shows the whole pipeline — issue triaged, PR risk-scored, gated,
  merged, deployed — moving in near-real time, so the agents' work is visible without reading the
  database. Backlog → Triaged → In progress → In review → Gated → Merged → Production, all
  computed fresh on every request from the existing tables (`sdlc/board.py`); there is no stored
  status field, matching every other signal in this system.
  - **`sdlc_gate_status`** is a small new read-model table (one row per PR, replaced in place,
    unlike the append-only `sdlc_agent_decisions` audit trail) that caches the risk-gate's current
    state so the board doesn't need to hit GitHub live. Written by `sdlc/gate_status.py`, on every
    poll, from `sdlc/runner.py`.
  - **Which deployment shipped a PR** is derived, not stored: the synthetic generator deploys
    strictly in date order and never skips a pending merged PR, so "the earliest same-source
    deployment at or after the PR's merge time" is a deterministic match, not a guess (see the
    docstring on `_pr_deployment` in `board.py`).
  - **Design calls made when the spec hit real-data gaps**, all picked with Geoff (2026-09-23):
    real issues never carry a sprint (nothing assigns one), so "In progress" only requires an open
    PR for a real card, not sprint membership — a real card is also never excluded by the sprint
    filter, regardless of which sprint is selected. There's no hosted deploy for this project, so
    real work stops at Merged; Production is populated by simulated history only.
  - **Frontend** (`apps/web/src/views/BoardView.vue` and `src/components/board/*`): polls the
    board endpoint every 15s with a highlight-flash on any card that changed column; filters for
    sprint (default: current), module, owner, and simulated-vs-real; a client-side **Replay**
    control re-plays the last N days (7/14/30/60) using each card's own `transitions` history — no
    extra network calls — then reverts to the live view. Clicking a card opens a detail drawer with
    its full timeline and the agent decision(s) behind it, signals and all.
- **Decision log: built and live-verified (2026-09-23).** The `/decisions` page in the web app —
  the direct answer to "prove this isn't a black box." Every row of `sdlc_agent_decisions`,
  newest first, server-paginated (`GET /api/v1/signals/decisions`, `sdlc/audit.py`'s
  `list_decisions`/`count_decisions`), filterable by agent, subject type, status and tier.
  Clicking a row opens a drawer with everything that row recorded: model, prompt version/hash,
  the version scored, latency and token counts, the raw structured output, the action taken, and
  — for a failed run — the raw error text. Live-verified against the real two bugs from the
  40-issue triage smoke test: filtering to `status=error` surfaces exactly those 27 rows, and
  opening one shows the original `BadRequestError` for the `confidence` schema bug, verbatim.
  Frontend: `apps/web/src/views/DecisionLogView.vue`,
  `src/components/decisions/DecisionDetailDrawer.vue`, `src/decisions.js` (pure formatting
  helpers, unit-tested) — uses Vuetify's server-side data table since this log is meant to grow
  for as long as the agents run, not stay small like a demo table.
- **Evaluation set: labelled by Geoff (2026-09-23), graded by `python -m sdlc.eval`.** Geoff's own
  module/type/points (and priority, notes) for the 40 real backlog issues, labelled blind on the
  labelling sheet, live in `orchestrator/eval/triage_eval_set.json`. (`backlog.yaml` is Cowork's and
  is not the eval set.) Bars fixed beforehand: module 85%, type 90%, points within one step 70%;
  priority reported, not gated.
  - **Grade blind, with `--fresh --yes`.** The triage prompt shows an issue's existing labels, and
    the 40 issues were created carrying Cowork's labels, so the stored smoke-test decisions echo
    Cowork (39/40 modules, 40/40 types, 34/40 exact points). `--fresh` re-runs the agent on each
    issue's saved text (`eval/_issues.json`) with no labels shown and similar examples drawn from
    simulated history only, records trial rows, and grades those (40 Haiku calls, about 8¢).
  - **Blind baseline (prompt `triage-v1`, 2026-09-23): module 88% pass, type 85% fail, points
    within one step 82% pass.** The type misses are one pattern: 6 issues Geoff called `chore`
    that the agent called `feature` (Salesforce stage mapping, email sync, webhooks, cursor
    pagination, the PR risk model, GitHub signal collection): integration, infrastructure and
    internal-tooling work. The prompt defines none of the types. **TODO:** Geoff's definition of
    `chore` goes into the prompt (as `triage-v2`), then one blind re-run. The eval set doubles as
    the tuning set, so change the prompt once for the pattern, not repeatedly to the score.
- **TODO:** what "selected suites" means (depends on the Phase 6 test-selector agent) and what
  the "manual QA" step for T3 consists of.
- One history is a noisy judge: with about 14 incident PRs, the top decile caught 27%–86% of them
  depending only on the random draw. So the rubric is graded on 30 generated histories pooled
  (`python -m sdlc.risk calibrate --generated 30`). The bars were fixed on 2026-09-20, before the
  first pooled run: T0's incident rate at most a quarter of the overall rate, and the top decile
  catching more than half of incident PRs. Both pass (0.20% vs 2.97%, and 59%), and a test locks
  them. The synthetic incidents come from the same factors the rubric reads, so this is a wiring
  check, not proof the score predicts real incidents. Re-run `calibrate` on real GitHub history
  once it exists, and tune weights, never outcomes.
- **Evaluation-set labelling sheet (2026-09-23):** a private claude.ai page
  (https://claude.ai/artifact/6nYqQUpMV1iemzkYJK6Bei) showing the 40 real backlog issues (#6–#45)
  as the agent saw them, with no agent or Cowork labels. Geoff's answers save to the page's own
  database (collection `labels`, one doc per issue: module/type/points, optional priority/note),
  which Claude reads with the ArtifactData tool. Source: `orchestrator/eval/` (template + issues).

### Phase 5 decisions (2026-09-23)

Branch `phase-5-forecasting`. The blueprint has no detailed Phase 5 spec; these were decided with
Geoff:

- **Epics exist in the data.** `sdlc_issues.epic` (migration `0006_issue_epic`); real issues get it
  from their `epic:<name>` label, and the synthetic history tags the last six sprints' feature work
  with four epics named like the real backlog's, plus 4–8 unscheduled stories each still to do (its
  own random stream, so the rest of the history and the risk calibration are unchanged).
- **Real issues are stories under epics.** Nothing assigns real issues a sprint, so the live demo
  moves an **epic's** forecast: a story opened under an epic pushes that epic's P50/P85 out. The
  sprint forecast covers simulated work only. GitHub milestones (real issues in sprints) were
  considered and left for later.
- **The planner agent proposes on the dashboard only,** stored in the audit table like every other
  agent decision. It never writes to GitHub (proposals name simulated items, and it would leave
  residue after every demo).
- **The forecast engine** (`sdlc/forecast.py`, `python -m sdlc.forecast`): Monte Carlo over the
  last six sprints' daily throughput, 10,000 runs, seeded per sprint/epic and day so a demo
  repeats. Sprints get P50/P85 and an on-time probability; epics get P50/P85 from their own pace.
  At-risk items come from module days-per-point, each with a plain-English reason.
- The synthetic history's current sprint was anchored two weeks back on odd ISO weeks (no sprint
  in progress); fixed, with a test for both parities.
- **The forecaster agent** (`sdlc/forecaster.py`) runs in the shared poll loop. It re-forecasts
  the current sprint or an epic only when its inputs fingerprint changes (a new day, a story
  added/closed/re-estimated, work starting), saving one `sdlc_forecasts` row (migration
  `0007_forecasts`, append-only) and one audit row (`subject_type` sprint/epic, `subject_id` =
  the forecast row) each. Triggers: `schedule` (first of the day), `change`, `manual`
  (`python -m sdlc.forecaster now`). No Claude calls and no GitHub writes, so it costs nothing;
  `ORCHESTRATOR_MODE=off` stops it. `synth --reset` forgets all saved forecasts.
  `forecaster.moved()` gives the latest forecast and how many days P50/P85 moved, for the
  dashboard. `trigger` is a MySQL reserved word: quote it in hand-written SQL.
- **Delivery forecast page** (`/delivery`, `apps/web/src/views/DeliveryForecastView.vue`, helpers
  in `src/forecast.js`): reads `GET /api/v1/signals/forecast` (the forecaster's saved rows via
  `forecaster.dashboard()`; it never runs a simulation itself) every 15s. The sprint's P50/P85,
  on-time chance, pace, at-risk items with reasons; each epic's dates, how far P50 moved and from
  what, and a trail of past forecasts; a flash when a subject gets a new forecast. `/forecast` is
  the CRM's sales forecast, a different thing.
- **The planner agent** (`sdlc/agents/planner.py`, runner `sdlc/plan_runner.py`, Sonnet 5 via
  `PLANNER_MODEL`, medium effort): runs after the forecaster in the poll loop when the sprint
  **slips** (its saved P85 is past its last day, i.e. on-time chance under 85%). It drafts up to
  three options (defer / reassign / split) once per slipping forecast; failures retry up to 3
  times, 5 minutes apart; at most 4 calls per sprint per day. Code drops any item or person the
  model names that it wasn't shown, clamps confidence, and **measures each defer option by
  re-running the same seeded simulation** without those items, so every date and percentage on the
  page comes from the forecast, never the model. Reassign/split effects are shown as not
  measurable. Proposes only: the draft is an audit row (`subject_type` sprint, `subject_id` = the
  forecast), shown on `/delivery` (marked out of date once the forecast moves on). `python -m
  sdlc.plan_runner dry-run` shows the request and a cost ceiling (about $0.03); `try --yes` makes
  one real call and records only a `trial` audit row; `synth --reset` clears planner rows with the forecasts.
