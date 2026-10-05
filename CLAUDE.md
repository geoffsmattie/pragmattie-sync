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
  deployment** and none should be added without asking. Relaxed once, by Geoff (2026-09-25): a
  **no-op deploy workflow** (`.github/workflows/deploy.yml`) runs on GitHub so the release gate and
  GitHub's deployment approval can be shown for real; it hosts nothing. **Changed permanently by
  Geoff (2026-09-26): development moves to GitHub** (agents doing the work, see "Agent
  development" below), with the local Docker stack kept as an emergency fallback. Most "deployments" and
  "incidents" are synthetic history; real ones are that workflow's no-op deploys and GitHub issues
  labelled `incident`.
- The plan lives in the blueprint doc ("PragMattie Sync: Predictive SDLC Orchestration
  Blueprint"). Phases: 1 Foundation ✅ · 2 CRM ✅ · 3 Signals + synthetic history ✅ · 4 First agents
  (triage + PR risk, governance tiers) ✅ · 5 Forecasting ✅ (#47, #48) · 6 Polish + client demo
  (on `phase-6-polish`).

## Stack (settled — don't swap without asking)

| Layer | Choice | Notes |
| --- | --- | --- |
| CRM API | Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 | `apps/api` (port 8000); Python 3.12 in Docker |
| Orchestrator | Python, FastAPI, same libraries, httpx, PyYAML | `orchestrator/` — a **separate service** (port 8001), see `docs/adr/0002` |
| Database | **MySQL 8.4 — not Postgres** | Docker service `db`; host port **3307** (3306 is taken on Geoff's PC); containers use `db:3306` |
| Front end | **Vue 3 — not React** — Vite, **Vuetify** (MIT), Pinia, Vue Router, Chart.js via vue-chartjs | `apps/web` (port 5173, and `http://pragmattie-sync.localhost` through the `proxy` service, Caddy, `proxy/Caddyfile`; decided 2026-09-26: `.localhost` needs no hosts-file edit and doesn't shadow a real domain). PrimeVue was rejected: v5 requires a license key |
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
                                # web also at http://pragmattie-sync.localhost (proxy on :80)
docker compose up --build -V    # after dependency changes (renews the node_modules volume)
docker compose exec api python -m app.seed --reset             # reset CRM demo data
docker compose exec orchestrator python -m sdlc.synth --reset  # regenerate engineering history
.\scripts\demo.ps1 reset -Apply     # between demos: CRM, history and GitHub back to a clean start
.\scripts\demo.ps1 check            # the pre-demo checklist (-Smoke also calls Claude, ~5 cents)
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
| **T2: Standard** | Risk 50–79, or touches Pipeline/Forecasting, or edits CI workflows or governance policies | AI review + 1 senior human | Full suite | Release gate checks |
| **T3: Critical** | Risk ≥ 80, or touches Billing/Auth, or schema migration | 2 humans incl. code owner | Full suite + manual QA | Human sign-off required |

- **Overrides:** a human can raise any PR's tier at any time; lowering a tier requires a
  written reason in the PR. Both go to the audit log. **Built (2026-09-23)** as a PR comment
  command read by the PR risk agent's poll (`sdlc/agents/overrides.py`): `/tier T3` raises (reason
  optional, and it **sticks** for the PR across later commits); `/tier T1 <reason>` lowers only
  with a reason of at least 10 characters, and only for the **commit it was made on** (a new push
  is new risk). **Nothing goes below a policy floor** (Billing/Auth, migrations,
  pipeline/forecasting): floors change in `tiers.yaml`, not by comment. Every command, accepted or
  rejected, is an audit row (`agent = tier_override`, `trigger = human`, `status` ok/rejected,
  `human_override` = from/to/actor/reason/why); the agent's own decision row keeps its own tier.
  The label, the gate, the simulated approver request and the comment's heading, override list
  and "what this tier needs" boxes all follow the tier in force.
- **Enforcement (planned):** the `main` ruleset will require a `risk-gate` status check.
  The PR risk agent sets it to pass only when the tier's approvals are present. Every agent
  decision is written to an audit table with its inputs, scores and the tier applied.
- Tiers will live in `orchestrator/policies/tiers.yaml` so they can be changed without code.
- Agents never merge, deploy or close issues beyond what their tier allows.
- **Highest tier wins** when several rows match (confirmed by Geoff, 2026-09-19): e.g. a
  low-risk PR with a schema migration is T3.
- **Approvers:** the "senior human" (T2) and the "code owner" (T3) are both **Geoff**
  (decided 2026-09-19). There is no `CODEOWNERS` file yet.
- **Deploy column:** the release gate, **built (2026-09-25)**; see "Release gate" under Phase 6
  decisions. (It replaced the 2026-09-19 plan of a dormant stub, when Geoff chose a no-op deploy.)

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
    filter, regardless of which sprint is selected. Real work reaches Production once the no-op
    deploy workflow ships its merge commit (or a later one); see "Release gate" under Phase 6.
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
    internal-tooling work. The prompt defined none of the types. The eval set doubles as the
    tuning set, so the prompt changes once for the pattern, not repeatedly to the score.
  - **`triage-v2` (2026-09-23)** defines the types. `chore` is Geoff's wording: "a change to the
    product that increases value and helps the product work better, but is not necessarily visible
    to the end user". `feature`, `bug`, the examples and the tie-breaker ("would the end user see
    the change?") are Claude's. **Blind re-run: module 90% pass, type 82% fail, points within one
    step 82% pass** (about 9¢). It fixed one chore miss (GitHub signal collection) but still called
    5 of Geoff's chores features (Salesforce stage mapping, email sync, webhooks, cursor
    pagination, the PR risk model), and called 2 of Geoff's features chores (#22 exchange rates,
    #38 structured JSON logging). The remaining misses look like a gap between the written
    definition and the labels, not something the agent can learn: by "visible to the end user",
    email sync and webhooks read as features and JSON logging as a chore.
  - **Decision (Geoff, 2026-09-23): accept and record.** Type stays failing at 82%; the 90% bar is
    not lowered and the 40 labels are not changed to match the agent. The type label never gates
    anything, so triage kept running in shadow on `triage-v2`. This set is now spent for tuning:
    no further prompt changes are graded against it.
  - **`triage-v3` (2026-09-24)** says who counts as a user per part of the product (CRM modules:
    reps, managers, customer admins, so API mechanics are chores; orchestrator: the engineering
    team, through what it shows them). Graded only on a **holdout set**: 20 invented issues
    (#9001–#9020, `eval/holdout_issues.json`) that Geoff labelled blind on 2026-09-24
    (`eval/triage_holdout_set.json`, sheet https://claude.ai/artifact/8Mk6FexGt8SLbkF7u8JoPK),
    same bars. `python -m sdlc.eval --set holdout --fresh --yes`; its trial rows are recorded as
    `synthetic`. **Result: module 90% pass, type 75% fail, points within one step 80% pass**
    (about 5¢). Type misses: #9006 (table move) and #9020 (token totals) Geoff feature / agent
    chore; #9015 (webhook retries) chore / feature; #9013 (API rate limit) and #9018 (key
    rotation) Geoff bug / agent feature or chore. The written rule and the labels still diverge
    (missing capability labelled as a bug; integrations as chores). At 20 issues each miss is 5
    points, so the two sets' type scores aren't directly comparable.
  - **Decision (Geoff, 2026-09-24): accept and record, again.** Type stays failing; the bar and
    labels stay as they are. Triage runs in shadow on `triage-v3`. The holdout set is now spent
    too. Type gates nothing on real issues (it's shown in comments, examples and planner context
    only), and a human correction sticks.
  - **If type is reopened:** first measure Geoff's own consistency (re-label ~15 of the 60 issues
    blind, shuffled, and compare with his earlier labels). At ~95% self-agreement, write the rule
    down and grade a `triage-v4` on a fresh holdout; at ~80%, the 90% bar is above what the labels
    support, and that is the finding to record.
- "Selected suites" (T0/T1) means the test selector's choice of CI jobs; see Phase 6 decisions.
  **TODO:** what the "manual QA" step for T3 consists of.
- One history is a noisy judge: with about 14 incident PRs, the top decile caught 27%–86% of them
  depending only on the random draw. So the rubric is graded on 30 generated histories pooled
  (`python -m sdlc.risk calibrate --generated 30`). The bars were fixed on 2026-09-20, before the
  first pooled run: T0's incident rate at most a quarter of the overall rate, and the top decile
  catching more than half of incident PRs. Both pass (0.20% vs 2.97%, and 59%), and a test locks
  them. The synthetic incidents come from the same factors the rubric reads, so this is a wiring
  check, not proof the score predicts real incidents. Re-run `calibrate` on real GitHub history
  once it exists, and tune weights, never outcomes.
  The Engineering signals page shows precision and recall at each tier threshold and both bars for
  this database's history (`GET /api/v1/signals/calibration`), saying plainly that one history is
  noisy (bar 2 fails in the current local history: 7 of 15) and that the pooled grading is the judge.
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

### Phase 6 decisions (2026-09-24)

Branch `phase-6-polish`. Scope from the blueprint: test selector, release gate, accuracy trend,
demo reset + pre-demo check (`sdlc.demo_reset`, `sdlc.demo_check`), logo and consulting-offer
slide, then the demo script, rehearsal and a recorded backup. The audit log view is already done
(the decision log).

- **Test selector: built (2026-09-24), recommendation only.** Decided with Geoff: it says which CI
  jobs a PR would need, but **CI still runs every job**, so each commit's real CI result shows
  whether skipping would have been safe. That record is its track record, as shadow mode is for
  `risk-gate`. Don't make CI skip jobs without asking: selection inside CI couldn't see the tier
  (the agents run locally and poll), and a skipped job reports success to the ruleset.
  - **Rules, no Claude** (`sdlc/agents/suite_select.py`): changed paths map to the four real CI
    jobs (`api`, `orchestrator`, `migrations`, `web`). Source under `apps/api` or `orchestrator`
    also selects `migrations` (it runs `alembic check` and seed/synth); a test-only change selects
    only its own job; docs/config select nothing. `.github/workflows/` or any path no rule covers
    selects every job, as does a tier whose `tests` in `tiers.yaml` starts "full suite" (T2, T3) or
    a failed risk assessment. Flaky flags: a job with 20+ runs in 60 days that failed then passed on
    a re-run at least 3% of the time; the flag says how many of those runs were simulated.
  - **Shown in the PR risk comment** as a "Tests" section (one bot comment per PR), rewritten when a
    person changes the tier with `/tier`.
  - **Audit rows** (`agent = test_selector`, `sdlc/suite_selector.py`), each numbered by `attempt`
    per commit: `poll` (the recommendation), `tier_change`, and `ci_result` once every CI job on
    that commit has finished, with status `missed` when a job it would have skipped really failed.
    Runs inside the PR risk agent's poll; looks for finished CI at most every 2 minutes, for 7 days.
    Reads GitHub Actions only, never writes to it. `python -m sdlc.suite_selector report` prints the
    track record (misses, failures caught, flaky re-runs, CI minutes it would have saved).
  - **Synthetic suites now match the real jobs**: `orchestrator` was added (its own random stream,
    so the rest of the history is unchanged; its CI failures do feed the risk rubric, and the
    pooled calibration bars still pass). `integrations-e2e` stays as a simulated-only flaky suite
    that the selector never picks. An existing database needs `sdlc.synth --reset` to get it.
- **Demo reset and pre-demo check: built (2026-09-24).** One command each, from the repo root in
  PowerShell: `.\scripts\demo.ps1 reset` (a dry run; `-Apply` to do it) and `.\scripts\demo.ps1
  check` (`-Smoke` also scores one real PR and triages one real issue with Claude, about 5 cents,
  recorded as trial rows). The blueprint asked for `python -m sdlc.demo_reset`; the CRM's seed runs
  in the `api` container, which the orchestrator can't reach, so the PowerShell script drives both
  (and pauses the agent loop during a reset). The Python halves are `sdlc/demo_reset.py` and
  `sdlc/demo_check.py`.
  - **The baseline** is a snapshot of the repository at a clean moment (issues with state and
    labels, PR numbers, branches), recorded with `demo.ps1 baseline` into
    `orchestrator/.demo/baseline.json` (git-ignored). Last recorded 2026-09-25: the 40 backlog
    issues open, 14 PRs, no open PRs, and the first real deployment. Nothing in the baseline,
    `main`, or any baseline branch is ever closed or deleted.
  - **Demo items are marked, not guessed (decided with Geoff, 2026-09-25):** the reset cleans up
    only issues and PRs labelled **`demo`**, and PRs from branches starting **`demo-`**. Real
    development in this repo (the PRs are this project building itself) is left alone, so its
    risk scores, CI record, release verdicts and deploys keep accumulating: that is where shadow
    mode's real sprint, the test selector's track record and any real accuracy trend come from.
    The reset lists what it kept. So in a demo: label every issue you open `demo` (incident
    reports too) and name PR branches `demo-...`. The `demo` and `incident` labels are created by
    `python -m sdlc.backlog --apply`, and the check confirms they exist.
  - **A reset** closes demo issues (GitHub can't delete them), puts backlog
    issues back to their baseline state and labels, closes demo PRs and deletes their agent
    comments, `tier:` labels and branches (in this repo, not in the baseline), reseeds the CRM,
    regenerates the simulated history for today (which forgets saved forecasts and planner
    drafts), forgets audit rows, simulated approvals and gate states about demo items, collects
    from GitHub and saves fresh forecasts. It lists what it left behind (merged demo PRs' commits,
    new branches with no PR, closed demo issues). The GitHub token needs Issues, Pull requests and
    Contents (branch deletion) write.
  - **The check** covers containers and the agent loop, the web app, both APIs, both databases'
    data, migrations at head, a sprint in progress, forecasts saved today, GitHub access, a clean
    start against the baseline, the release gate's GitHub setup (deploy workflow, both
    environments, the sign-off reviewer, the token's Deployments access), and `ORCHESTRATOR_MODE`
    (off fails, shadow warns: the demo needs enforce). Exit code 1 on any failure.
- **Accuracy trend: built (2026-09-25), decided with Geoff.** The `/accuracy` page ("Prediction
  accuracy"), from `GET /api/v1/signals/accuracy` (`sdlc/accuracy.py`; no Claude, no GitHub calls;
  the two simulated trends are cached per day and history, about 5 seconds to build). Four trends,
  each labelled simulated or real:
  - **Delivery forecasts (simulated):** a backtest. Each finished sprint is forecast again as of
    its third working day by the forecaster's own seeded engine, using only what was known then,
    and its P50/P85 checked against when its last item closed. Targets: P85 met ~85%, P50 ~50%.
    Sprints with no throughput behind them are skipped. First result (2026-09-25, 11 sprints): P85
    82%, P50 36%, and the P50 error shrinks from weeks too cautious in early sprints (thin
    history) to a few days.
  - **Risk score (simulated):** per sprint, incident PRs the rubric put at T2+ (12 of 15, 80%, one
    at T0). Real PRs are reported as counts: none has caused an incident yet.
  - **Triage (real):** per week, issues the agent labelled and how many a person changed since.
    The triage poll now stores each issue's current labels (it reads them every poll anyway).
    Kept labels can echo existing ones; the blind `sdlc.eval` stays the stricter test.
  - **Test selector (real):** per week, settled commits and misses.
  - Real trends draw only from 5 data points; below that they show counts.
- **Release gate: built (2026-09-25), level 3 (a real no-op deploy), decided with Geoff.** Rules
  only, no Claude. Rules in `sdlc/agents/release_gate.py`, settings in `tiers.yaml`
  (`release_gate:` and each tier's `release: automatic|checks|signoff`).
  - **A release is everything merged since the last deploy** (you deploy `main`, not a PR), at the
    highest tier among its PRs. T0/T1 deploy automatically; T2 needs the checks: CI passed on the
    release commit, no open incident in a module it touches, and at most 30% of the last 7 days'
    deploys causing incidents (with at least 3 to judge); T3 needs the checks and then **Geoff
    approves the deployment in GitHub** (the `production-signoff` environment's required
    reviewer). Verdicts: release (`success`), hold (`pending`, clears by itself), blocked
    (`failure`: CI failed on that commit, so only a new commit releases). A PR's risk-gate isn't
    re-checked: once merged, its sign-off can't change. Every verdict change is an audit row
    (`agent = release_gate`, `subject_type = release`, `subject_id` = the PR whose merge made the
    commit).
  - **Real releases** (`sdlc/release_runner.py`, in the shared poll loop): the deploy workflow runs
    on every push to `main` and waits (up to 60 minutes, then fails closed) for a `release-gate`
    commit status, which the runner posts; T3 then waits for the Approve button. The workflow
    deploys nothing but GitHub records a real deployment, which the collector stores (with its
    commit), so real cards reach Production. **Real incidents are GitHub issues labelled
    `incident` + `module:<name>`** (optional `sev1`–`sev3`): open = ongoing, closed = resolved;
    they're stored as incidents, not work, and the triage agent skips them. Deploy-workflow runs
    are never counted as CI.
  - **Simulated history:** every simulated deploy goes through the same rules and a hold keeps
    the whole release for a later day (a T3 change waits for a simulated sign-off 4 hours after
    merge, always labelled simulated). Deploy and incident draws come from per-day and per-PR
    streams, so holds move only deploy and incident times. Effect: about 67 deploys instead of
    78 per history, and holds are mostly sign-off and failure-rate. The pooled calibration bars
    still pass (0.17% vs 2.97%, and 58%).
  - **Demo flow:** open an issue labelled `incident` + `module:pipeline` + `demo`, merge a
    pipeline PR from a `demo-` branch (a
    T2 floor), and the deploy is held ("T2 · Held: open incident in pipeline (#n)") on GitHub, the
    board (a "Release held" chip on the merged card) and the decision log; close the issue and it
    deploys. A billing/auth or migration PR shows the Approve deployment button.
  - **Needs for a demo:** `ORCHESTRATOR_MODE=enforce` (shadow only says what it would do, so
    nothing is held), then **shadow again afterwards**; the stack and agents running throughout;
    Geoff signed in to GitHub to approve; 1–3 minutes between merge and verdict. Migration
    `0008_release_gate` adds `merge_commit_sha` to PRs and `external_id`/`sha` to deployments and
    incidents.
  - **One-time GitHub setup (Geoff):** Settings > Environments: create `production`, and
    `production-signoff` with yourself as required reviewer ("Prevent self-review" off); give the
    token **Deployments: read and write**; re-record the demo baseline
    (`python -m sdlc.demo_reset baseline --force`) once the repo is clean, so it lists deployments.
  - **The demo reset** also takes the `incident` label off demo incident issues (and closes them),
    forgets their incident rows, marks demo deployments inactive and deletes them, and forgets
    release-gate rows about demo PRs. `release-gate` statuses on `main`'s commits can't be deleted.

### Agent development: the agentic rebuild (decided 2026-09-26, not built yet)

Geoff's direction: the project is **rebuilt entirely by agents**, with Geoff as technical project
manager / product manager and, later, one or two human developers in the loop where risk calls
for a person. Decided with Geoff:

- **A new public repository, `pragmattie/pragmattie-sync-agentic`**, built from scratch by agents.
  This repository (v1) stays the working demo until the rebuild overtakes it.
- **v1 governs v2:** this repo's agents (triage, PR risk, test selector, release gate, accuracy)
  are pointed at the new repository, so every agent PR there is tiered, gated and audited here.
  The story: "a governance system supervised AI agents rebuilding the whole product."
- **Runs in GitHub** (permanent change to the local-only rule): the implementer agent runs in
  GitHub Actions on the new repo; the local stack stays as an emergency fallback and hosts v1's
  governance for now.
- **Stays public, "all rights reserved"** (Geoff, 2026-09-28): no open-source licence, so the code is
  readable but not reusable. Private was ruled out because, short of GitHub Enterprise, required
  reviewers on environments (the T3 Approve deployment button) exist only on public repos, and our
  app can update a Projects board only in an organization. Public repos also get unlimited Actions
  minutes (private: 3,000/month on Pro).
- **The sprint board moves to a GitHub Projects board** and the development metrics to a separate
  **Delivery Insights** app; the CRM app shows only the product (decided 2026-09-27, details in the
  rebuild plan). The repo moves into a free GitHub organization, **`pragmattie`** (Geoff,
  2026-09-28), so the app can update the board. **The separation applies to the rebuild only;** v1
  keeps its single app. Plan approved 2026-09-28 (82 issues): clean room, parity by default and
  redesign by decision.
- **A GitHub App** gives the agents their own identity (Geoff gave permission), so their PRs aren't
  authored by Geoff and he can approve them with real GitHub reviews.
- **Models (superseded 2026-10-01: Opus 5.5 is now the default for every build, see below):**
  Sonnet 5 by default; Opus 5.5 for T3, chosen by rule in the rebuild's
  `.github/workflows/implement.yml` (moves to its `tiers.yaml` at M4): a `model:opus`/`model:sonnet` label on the issue wins, then the PR's actual tier, then
  the issue's `forecast:Tn` label. Every run's model is in the audit trail. **No automatic step-up to
  Opus after a failed Sonnet run** (Geoff, 2026-09-27). **Reminder:** issue #1 in the agentic repo,
  assigned to Geoff, to re-evaluate at the M1 gate, after 20 agent runs, or after 3 Sonnet failures
  in a row; the implementer workflow must comment there on every Sonnet run that ends with failing
  tests. When any of those triggers is reached, remind Geoff. **Re-evaluated and kept
  (Geoff, 2026-10-01):** issue #1 closed at the M1 gate; after 9 builds (Opus 5: 14–28 turns,
  $0.36–0.90, no failures; Sonnet 4: 32–51 turns, $0.55–1.40, one turn-limit failure on 1.8),
  **Sonnet stays the default and `model:opus` is added case by case** (first: 1.8's retry).
  **Changed the same day (Geoff, 2026-10-01): Opus 5.5 is the default for every build**, after
  Sonnet hit its turn limit on 1.9 too (54 turns, $1.34; two failures in a row) while Opus
  finished 1.8 in 19 turns for $0.68. A `model:sonnet` label on an issue still chooses Sonnet.
  Reviews were already always Opus (see the shadow reviewer below).
- **Budget:** $100/month for the first month as a pilot (hard limit in the Anthropic Console, plus
  per-run and daily caps in code, every run an audit row), then decided from measured cost per
  issue. Estimate for the whole rebuild (~22k lines, 70-100 issues): $250-500 on Sonnet 5; about
  $150/month over 2-3 months; Geoff's review time (25-50 hours) is the real limit.
- **Geoff approves everything at first**, whatever the tier; auto-merge only later, with a record.
- **Order:** (1) setup: repo, GitHub App, secrets (Geoff's clicks); (2) the rebuild plan: the current
  system turned into an ordered backlog of specs, **approved by Geoff before any code is written**;
  (3) the implementer workflow, run on 2-3 small issues first, with measured cost reported.
- **v1 governs the rebuild (built 2026-09-28, branch `phase-7-agentic-governance`).** The
  rebuild's rows use **`source = agentic`** (alongside `synthetic` and `github`), so its issue and PR
  numbers never collide with v1's. `GITHUB_TOKEN_AGENTIC` (a second fine-grained token owned by the
  `pragmattie` organization) and `github_repo_agentic` in `sdlc/config.py` switch it on; without the
  token only v1's own repository is governed. The poll loop then runs a second set:
  `rebuild:pr_risk`, `rebuild:triage`, `rebuild:release_gate` (idle until the rebuild has a deploy
  workflow) and `rebuild:implementer_runs`. Each runner and the `Collector` take a `source`; the
  test selector settles CI per source with that repository's client.
  - **Implementer runs in the audit trail** (`sdlc/agent_runs.py`): the rebuild's workflow posts
    `<!-- pragmattie-run {...} -->` on the issue after each run; only `github-actions[bot]`
    comments count. One row per run: `agent = implementer`, `subject_source = agentic`,
    `head_sha = run-<id>`, model, tokens, cost (in `output`), `status` ok or error.
  - **v1's own pages leave the rebuild out:** metrics (`REBUILD` filter), the board (unless asked
    for `source=agentic`) and the risk calibration. The decision log shows rebuild rows as
    "Rebuild Issue #n", with an "Implementer (rebuild)" agent filter. The rebuild's metrics belong
    in its own Delivery Insights app.
- **M0 complete (2026-09-30):** 0.2–0.8 built by agents, CI live with four required checks on the
  agentic repo's `main`, about $5.41 of agent spend.
- **M1 specs written into issues #11–#21 (2026-09-30)**, from v1's behaviour (parity). **1.5
  "Activities and the account timeline" moved to the "next" list** (Geoff: it isn't in v1), #15
  closed as not planned; 2.5 drops "timeline" too. M1 runs strictly in order (1.1, 1.2, 1.3, 1.4,
  1.6, 1.7, 1.8, 1.9, 1.10, 1.11) because each migration builds on the one before. Specs are
  written with `scripts/ghwrite.py` (issues only: body, comment, close, labels).
  **API money stays a JSON string with 2 decimal places** (Geoff, 2026-09-30: exact, and as v1
  does); a `PATCH` with `owner_id: null` clears the owner. Both are in 1.8's spec (#18).
- **Towards less review (Geoff asked 2026-09-30; decided with him).** After 8 merged agent PRs
  (none reverted, one changed by review) the record is good but thin, and v1 mis-tiered 3 of about
  12 PRs, so nothing merges without Geoff yet. Built instead:
  - **Auto-start:** merging an agent PR starts the next open item in the same milestone, if its
    spec is approved (no `needs-info` label). It never crosses a milestone: that gate is Geoff's.
    T2/T3 still stop for `/approve-plan`. (`implement.yml`, on `pull_request: closed`.)
  - **A shadow reviewer agent** (`review.yml` in the agentic repo): on every agent PR and new
    commit it checks the change against the issue's spec and the repo's CLAUDE.md, read-only, and
    rewrites one comment: would approve / would request changes, findings by severity, and the
    criteria it checked. **Opus 5.5 for every review** (2026-09-30: Sonnet 5 reviews took ~30
    turns, one ran out of turns, and one re-review of #106 returned a placeholder "test" marked
    approve; Opus reviewed #104 fully in 8 turns). A verdict needs a summary of 80+ characters
    and 3+ criteria checked, else it is recorded as `invalid`. **Exclude run 36767766998
    (`review-36767766998`, PR #106) from any comparison: it is that placeholder, recorded as an
    approval before the guard existed.** `/review` on an agent PR asks for a fresh review. Its
    cost counts toward the daily cap. v1
    records each reviewed commit (`agent = reviewer`, `subject_type = pr`,
    `head_sha = review-<run>`; `python -m sdlc.peek reviews`). **At the M1 gate, compare its
    verdicts with Geoff's decisions** before delegating anything.
  - **Floor `governance_files` (T2):** a PR that edits `.github/workflows/` or
    `orchestrator/policies/` is at least T2 (`touches_governance`, migration
    `0009_pr_touches_governance`). `ci/proposed/` doesn't count: it does nothing until applied.
  - **T0 auto-merge: taken at the M1 gate (Geoff, 2026-10-01).** Gate read: CI green on every
    PR; the reviewer approved all PRs Geoff merged except #118 (it objected to the empty
    description of a PR Geoff opened himself) and was once too lenient (#116, an unmet rule filed
    as a note); one borderline tier call (#105) and none near T0. Built:
    - **`risk-gate` decides the rebuild's merges** (`ORCHESTRATOR_MODE_AGENTIC=enforce`; v1's own
      repository stays in `ORCHESTRATOR_MODE`). In the rebuild, T0 passes only when the AI
      reviewer's newest verdict on that exact commit is "approve" (`gate.py`'s
      `needs_ai_review`); T1+ pass on a person's sign-off, and **a person's GitHub approval of
      the PR's current commit counts as that sign-off** (the rebuild's PRs are authored by a bot,
      so Geoff can approve them). T3 still needs manual QA and the simulated second approval.
    - **Every agent PR is set to auto-merge** (`implement.yml`), so GitHub merges it once CI and
      `risk-gate` pass: T0 with no person, T1+ as soon as the approval lands.
    - **Fails closed:** with v1's stack down, `risk-gate` never reports and nothing merges
      (Geoff's ruleset bypass still works).
    - T1 without a person stays a separate decision (the blueprint gives T1 one human); T2 and T3
      always keep one.
  - **T0 stays narrow (Geoff, 2026-10-01).** In M2 v1 rated 2.9 (branding) T1 at score 37, not
    the forecast T0: almost every rebuild item is code, so real T0s will be rare (docs/config).
    Geoff asked whether to make T0 easier; decided **not to move thresholds or widen "docs only"**
    without evidence. Geoff may lower a PR himself with `/tier T0 <reason>` (floors still hold).
  - **Next, after M2: test the reviewer before trusting it further.** Its record is ~12 valid
    verdicts, all "approve": it approves good work, but its **catch rate** is unknown. Plan,
    with bars **fixed now, before the run** (2026-10-01):
    - 5 PRs with one planted defect each, against real specs: a spec rule left out, a real bug,
      a test that can't fail, a forbidden change (e.g. a workflow or CLAUDE.md edit), and scope
      creep. Plus 2 control PRs that are correct. None is ever approved or merged; all are closed
      after review and labelled so they're easy to find. Roughly $2–3.
    - **Pass:** at least **4 of 5** defects caught as a **blocker** (verdict "request changes"),
      the forbidden change always caught, and **neither control** wrongly rejected.
    - **Result (2026-10-02): PASS.** PRs #135–#141 (closed unmerged, labelled `reviewer-test`):
      **5/5 defects caught** as "request changes", with correct, specific reasons (A rule
      omitted, B last-day-of-quarter bug, C assertion accepting 200, D CLAUDE.md edit quoting
      rule 5, E DELETE endpoint plus the weakened convention test); **both controls approved**.
      **B, C and D had green CI**: only the reviewer stopped them. Control F first came back
      "request changes": my construction left one blank line where `ruff format` needs two, and
      CI failed on exactly that, so the reviewer was right; F was fixed (formatting only) and
      re-reviewed, approve. Cost about $2.60 (8 Opus reviews).
    - **Rung taken (Geoff, 2026-10-02): a 1-hour objection window for front-end-only T1 PRs.**
      `tiers.yaml` `objection_window` (tiers [T1], 60 minutes, paths `apps/crm-web/`,
      `apps/insights-web/`; T2/T3 can never be listed, the loader refuses). In the rebuild, a T1
      PR whose changed files are all under those paths, that the AI reviewer approved on its
      current commit, counts as signed off 60 minutes after that approval unless a person
      comments `/hold` (any `/hold` from a non-bot stops it for that PR; a person's approval
      still merges at once). While waiting, `risk-gate` says "merges after HH:MM UTC". Each
      window sign-off is an audit row (`agent = objection_window`, `head_sha = window-<sha>`,
      tier, the reviewer approval it rests on), so the trail always shows no person approved.
      API, orchestrator and mixed PRs keep a person's sign-off. Next possible rungs (not taken):
      widen the paths, or T1 everywhere, after a record of window merges with no reverts.
    - **The bar for T1 everywhere (Geoff, 2026-10-05, fixed before counting):** the objection
      window (60 minutes, `/hold` still stops it) widens from front-end-only to **every T1 PR**
      once **10 T1 PRs in a row** merge clean, with **no reverts** among them. Counted from
      2026-10-05, after #162 (4.3); reported at each merge.
      - **Counts:** a T1 agent PR (its final tier) where the AI reviewer's first verdict was
        "approve" and it merged with no `/revise`, no human commit and no later fix for something
        the review missed. Front-end PRs merged by the window count too.
      - **Resets to 0:** a T1 PR the reviewer approved that then needed a change (like #160's
        module rate, caught by a person), or any revert of a counted PR.
      - **Neutral:** the reviewer says "request changes" and is right (it worked), or is stricter
        than needed and is overruled (safe).
      - Why now and not sooner: of M4's first three T1 PRs, #158 and #160 needed changes, and
        the reviewer approved #160 before a person caught its gap. T2 and T3 always keep a
        person; `tiers.yaml` refuses to list them.
    - **If it passes,** the next rung is **T1 auto-merge with an objection window**: a T1 PR that
      the reviewer approves (and CI passes) merges after a waiting period unless Geoff comments
      "hold"; start with front-end-only T1 PRs. **If it fails,** fix the reviewer's prompt once for
      the pattern, and re-test on fresh planted defects (never tune to the same set).
- **The demo story (Geoff, 2026-10-04):** "I built the governance layer first; then AI agents
  built the entire product under it, including the next version of the governance layer, which now
  runs the show." The audience never hears of a pivot from simulated developers to agents. So:
  1. **The real agent build is the headline** in v2's Delivery Insights: the agentic repo's issues,
     PRs, tiers, reviews, CI and cost. Simulated history stays (risk calibration needs incidents),
     but it is labelled as calibration data used to test the models and never presented as a team.
  2. **Forecast the real build:** the milestones (GitHub milestones M0–M7) are the epics, and the
     forecast predicts when each finishes at the agents' pace.
  3. **The whole trail lives in v2:** #157 (7.4) imports v1's decisions about the rebuild into
     v2's audit trail before cutover, marked as decided by v1; v1's database dump is kept too.
  4. **The sprint board is on GitHub now:** a Projects board in the `pragmattie` organization with
     every agentic issue, closed ones included, grouped by milestone, using GitHub's built-in
     workflows until 4.15–4.16 take over.
  5. **The M6 demo script follows this story:** the board, one PR's risk comment and gate, the
     decision log, the live forecast, then a live issue triaged, built, tiered and gated.
  Specs from M4 batch 2 onwards (and M5, M6) are written to fit.
- **M4 decisions (Geoff, 2026-10-04):** v1's rebuild-era features are folded into M4 (the
  governance floor in 4.1, run records in 4.4, the reviewer gate, GitHub approval as sign-off and
  the objection window in 4.7, conditional reads in 4.9). The board goes live at 4.16: v2's board
  updater runs against the agentic repo from then; the rest of v2 stays offline until 7.1. Specs
  come in three batches: 4.1–4.7 (approved 2026-10-04), 4.8–4.14, 4.15–4.21.
- **TODO:** the human developers' GitHub usernames (they would replace the simulated second
  approver).
