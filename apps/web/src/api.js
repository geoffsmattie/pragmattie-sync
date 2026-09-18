// Base URL for the FastAPI backend. Override with VITE_API_URL in apps/web/.env.local.
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export async function getJson(path) {
  const response = await fetch(`${API_URL}${path}`)
  if (!response.ok) throw new Error(`${path} returned ${response.status}`)
  return response.json()
}
