"""What each module is, in one line. Shared by anything that explains a module to a person or
a model: the triage agent's prompt today, and the PR risk agent could use it later.
"""

from sdlc.tables import MODULES

MODULE_DESCRIPTIONS: dict[str, str] = {
    "leads": "Lead capture, scoring, import, duplicate detection, assignment rules.",
    "accounts": "Accounts, contacts, account hierarchy and merge, account timeline.",
    "pipeline": "Deal stages and the pipeline board, stage history, bulk stage updates.",
    "forecasting": "Quota, weighted forecast, forecast snapshots, rollup math.",
    "integrations": "Email/calendar sync, webhooks, CSV import/export, third-party APIs.",
    "billing_auth": "Sign-in, SSO, roles and permissions, seat billing, plan upgrades.",
    "orchestrator": "The predictive SDLC layer itself: signals, agents, tiers, the dashboard.",
    "platform": "Cross-cutting: API infrastructure, search, job queue, audit logging.",
}

assert set(MODULE_DESCRIPTIONS) == set(MODULES), "every module needs a one-line description"
