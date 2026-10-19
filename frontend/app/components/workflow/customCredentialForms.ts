// Node types whose credentials are created through a custom form whose inputs depend on node-specific config
// (agent → selected model, mcp-server → server URL). NodeCredentials maps each to its form; this list stands
// apart so the pages that only filter by it (Connections, the create-credential dialog) don't load the forms.
export const CUSTOM_CREDENTIAL_FORM_TYPES = ['agent', 'mcp-server'] as const;

export type CustomCredentialFormType = (typeof CUSTOM_CREDENTIAL_FORM_TYPES)[number];

/**
 * Whether a node type's credentials are created through a custom form. Such credentials can't be created
 * standalone outside a node, so the create-credential dialog excludes these node types from its service list.
 */
export function hasCustomCredentialForm(nodeType: string): boolean {
    return (CUSTOM_CREDENTIAL_FORM_TYPES as readonly string[]).includes(nodeType);
}
