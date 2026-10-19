// What a deployment adds to a visitor's public session (/api/public-session, read by usePublicSession). Each field is
// read from the request on the server, so a cached marketing page learns per-visitor state without reading cookies
// itself (only Supabase's storage adapter does: backend/tests/test_frontend_auth_invariants.py). The engine
// registers none.
export type PublicSessionField = (request: Request) => string | null;

const fields = new Map<string, PublicSessionField>();

export function registerPublicSessionField(name: string, read: PublicSessionField): void {
    fields.set(name, read);
}

export function readPublicSessionFields(request: Request): Record<string, string | null> {
    return Object.fromEntries([...fields].map(([name, read]) => [name, read(request)]));
}
