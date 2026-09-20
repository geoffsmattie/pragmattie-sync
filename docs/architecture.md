# Architecture

PragMattie Sync is a monorepo with two parts:

1. **The product:** PragMattie Sync CRM (`apps/api` FastAPI + MySQL, `apps/web` Vue 3 + Vuetify).
2. **The orchestration layer:** (`orchestrator/`, a separate service on port 8001) collects engineering signals, predicts delivery risk and delay, and runs AI agents that act on those predictions under risk-based governance tiers. See [ADR 0002](adr/0002-orchestrator-as-a-service.md).

```mermaid
flowchart LR
  A[GitHub events] --> B[Signals store<br/>MySQL]
  B --> C[Prediction models]
  C --> D[Agents<br/>Claude API]
  D --> E{Governance tier}
  E -->|low risk| F[Auto-act]
  E -->|high risk| G[Human approval]
  F --> H[Dashboard]
  G --> H
```

See the full blueprint for the agent roster, models, tiers and phased plan.
