#!/usr/bin/env bash
# The project's own checks, as fixed commands, so they can run without a prompt each time.
#
#   bash scripts/check.sh orchestrator [pytest args]   # ruff + pytest in the orchestrator container
#   bash scripts/check.sh api [pytest args]            # ruff + pytest in the CRM API container
#   bash scripts/check.sh web                          # vitest + production build in the web container
#   bash scripts/check.sh workflows [repo folder]      # actionlint on a repo's .github/workflows
#                                                      # (default: this repo; e.g. ../pragmattie-sync-agentic)
#   bash scripts/check.sh workflow-file FILE           # actionlint on one workflow file anywhere
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  orchestrator|api)
    service=$1; shift
    docker compose exec -T "$service" sh -c "pip install -q -r requirements-dev.txt >/dev/null 2>&1; \
      ruff check . && ruff format --check . && pytest -q --no-header -p no:cacheprovider $*"
    ;;
  web)
    docker compose exec -T web sh -c "npx vitest run && npm run build"
    ;;
  workflows)
    folder=$(cd "${2:-.}" && { pwd -W 2>/dev/null || pwd; })
    MSYS_NO_PATHCONV=1 docker run --rm -v "$folder:/repo" -w /repo rhysd/actionlint:1.7.7 -color=false
    ;;
  workflow-file)
    folder=$(cd "$(dirname "$2")" && { pwd -W 2>/dev/null || pwd; })
    MSYS_NO_PATHCONV=1 docker run --rm -v "$folder:/w" -w /w rhysd/actionlint:1.7.7 -color=false \
      "$(basename "$2")"
    ;;
  *)
    sed -n '2,9p' "$0"; exit 2
    ;;
esac
