// Turns a raw node-execution error into a concise, actionable message for
// toasts/notifications. Recognises the common "unresolved reference" failures
// (a workflow variable that isn't set, or an upstream node output that hasn't
// been produced) and explains what to do; anything else falls back to the
// raw error text so no information is lost.

export interface NodeErrorMessage {
    title: string;
    description: string;
}

/**
 * @param nodeName  user-facing label of the node that failed
 * @param rawError  the backend's node error string
 */
export function describeNodeError(nodeName: string, rawError: string): NodeErrorMessage {
    const ref = rawError.match(/\{\{\s*([^}]+?)\s*\}\}/)?.[1]?.trim();
    const isUnresolvedRef = !!ref && /not resolved/i.test(rawError);

    if (isUnresolvedRef && ref) {
        // {{vars.X}} — a workflow variable hasn't been set. Variables are
        // populated by the workflow's Setup step or by set-variable nodes.
        if (ref.startsWith('vars.')) {
            const varName = ref.slice('vars.'.length).trim() || ref;
            return {
                title: 'Setup may be needed',
                description: `"${nodeName}" needs the "${varName}" value, which hasn't been set. `
                    + `Complete the workflow's Setup — or run the node that sets it — then try again.`,
            };
        }
        // {{someNode.field}} — an upstream node output isn't available yet.
        return {
            title: 'Missing an input',
            description: `"${nodeName}" needs "${ref}" from an earlier node that hasn't run. `
                + `Run the upstream nodes first.`,
        };
    }

    // Unknown failure — surface the raw error verbatim.
    return {
        title: `${nodeName} failed`,
        description: rawError,
    };
}
