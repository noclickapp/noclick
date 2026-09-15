// Auth for browser → backend REST calls (`${VITE_API_URL}/...`).
//
// The session cookie is SameSite=Lax and scoped to the app domain, so
// `credentials: 'include'` never sends it to the API domain cross-origin in
// prod (Developer-tab API keys 401'd on every request, 2026-09-15) — and it can
// go stale vs the auto-refreshed session. The live Supabase access token as a
// Bearer header avoids both; the backend prefers it and falls back to the
// cookie for same-origin callers (`utils.auth.authenticate_http_request`).

import { getExistingBrowserClient } from '~/lib/supabase-client';

export async function backendAuthHeaders(): Promise<Record<string, string>> {
  const client = getExistingBrowserClient();
  if (!client) return {};
  try {
    const { data } = await client.auth.getSession();
    const token = data.session?.access_token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}
