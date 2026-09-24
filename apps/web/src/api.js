// Base URL for the FastAPI backend. Override with VITE_API_URL in apps/web/.env.local.
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
// The orchestrator (predictive SDLC layer) runs as its own service.
export const ORCH_URL = import.meta.env.VITE_ORCH_URL ?? 'http://localhost:8001'

function buildUrl(path, params, base = API_URL) {
  const url = new URL(`${base}${path}`)
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === '') continue
    for (const v of Array.isArray(value) ? value : [value]) url.searchParams.append(key, v)
  }
  return url
}

async function handle(response, path) {
  if (response.ok) return response.json()
  let detail = `${path} returned ${response.status}`
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') detail = body.detail
    else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg).join('; ')
  } catch {
    // not JSON; keep the generic message
  }
  const error = new Error(detail)
  error.status = response.status // the service answered: this is its error, not a lost connection
  throw error
}

/** A message for a failed orchestrator call. Only a request that got no answer at all suggests
 * the service is down; an error it sent back (a bad filter, say) is shown as it is. */
export function orchErrorMessage(err) {
  if (err.status) return err.message
  return `${err.message}. Is the orchestrator service running on port 8001?`
}

export async function getJson(path, params) {
  return handle(await fetch(buildUrl(path, params)), path)
}

/** GET from the orchestrator service instead of the CRM API. */
export async function getOrchJson(path, params) {
  return handle(await fetch(buildUrl(path, params, ORCH_URL)), path)
}

export async function sendJson(method, path, body) {
  const response = await fetch(buildUrl(path), {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  return handle(response, path)
}
