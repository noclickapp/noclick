// The single source of truth for "what UI does a credential method need". Every
// credential model declares its kind via the `x-credential-type` schema extension
// (oauth / qr_scan / absent→api_key); agent CLI sign-ins are their own kind. Both the
// in-app credential UI (from the JSON schema) and the public provide page (from the
// backend method) derive the kind HERE and render through the CredentialMethodConnect
// registry — so dispatch can't drift, and adding a kind is one registry entry.

export type CredentialMethodKind = 'api_key' | 'oauth' | 'agent_oauth' | 'qr_scan';

/** Map an `x-credential-type` value to a schema-backed UI kind. Unknown/absent → api_key
 *  (plain fields), which is the correct default for any field-based credential. */
export function kindFromCredentialType(xCredentialType: string | null | undefined): CredentialMethodKind {
    switch (xCredentialType) {
        case 'oauth': return 'oauth';
        case 'qr_scan': return 'qr_scan';
        default: return 'api_key';
    }
}

/** Resolve the kind of a backend-enumerated auth method (GET /credential-request/{token}).
 *  Trusts the backend's authoritative `method_kind`; agent CLI sign-in is flagged
 *  separately, and a legacy method without `method_kind` falls back to is_oauth. */
export function kindFromBackendMethod(m: {
    method_kind?: string | null;
    is_oauth?: boolean;
    agent_oauth_kind?: string | null;
}): CredentialMethodKind {
    if (m.agent_oauth_kind) return 'agent_oauth';
    if (m.method_kind) return m.method_kind as CredentialMethodKind;
    return m.is_oauth ? 'oauth' : 'api_key';
}
