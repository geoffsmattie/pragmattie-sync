// Base URL for the FastAPI backend. Override with VITE_API_URL in apps/web/.env.local.
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function buildUrl(path, params) {
  const url = new URL(`${API_URL}${path}`)
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
  throw new Error(detail)
}

export async function getJson(path, params) {
  return handle(await fetch(buildUrl(path, params)), path)
}

export async function sendJson(method, path, body) {
  const response = await fetch(buildUrl(path), {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  return handle(response, path)
}
