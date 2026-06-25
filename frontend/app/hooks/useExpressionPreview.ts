// Debounced live preview for inline expressions, showing the computed result.
// Sends the expression plus the connected nodes' sample/last outputs to the backend,
// which runs the same sandboxed evaluator the runtime uses, and returns the computed
// value (or an error message). Added for inline expressions.

import { useEffect, useRef, useState } from 'react';
import type { Node } from '@xyflow/react';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowNodeEvaluateExpressionRequest } from '~/types/socket-events.generated';
import { useReferenceAutocomplete } from '~/components/workflow/ReferenceAutocompleteContext';

export interface ExpressionPreviewState {
    loading: boolean;
    /** Value kind: 'object' | 'array' | 'string' | 'number' | 'boolean' | 'null'. */
    kind?: string;
    /** Object keys (for the Fields chips); null for non-objects. */
    keys?: string[] | null;
    /** Pre-formatted, clipped display string for the output preview. */
    preview?: string;
    /** Typed tokens for the output preview (so the UI can highlight keys). */
    previewTokens?: Array<{ t: string; v: string }>;
    error?: string;
    /** True once a non-empty expression has been evaluated at least once. */
    hasResult: boolean;
}

const DEBOUNCE_MS = 350;

// Build the sample-output map (node id -> last/mocked output) the backend evaluates
// against, plus the `$json` primary input (the single direct upstream output).
function buildSampleOutputs(
    inputNodes: Node[],
    workflowVariables?: Record<string, unknown>,
    expectedSchemas?: ReadonlyMap<string, unknown>,
) {
    const sampleOutputs: Record<string, unknown> = {};
    for (const n of inputNodes) {
        // Real output (mocked or last run) wins; otherwise fall back to the clipped
        // schema sample so a reference to a not-yet-run node still previews instead of
        // erroring "no data for node".
        const out =
            n.data?.mockedOutput !== undefined ? n.data.mockedOutput
            : n.data?.output !== undefined ? n.data.output
            : expectedSchemas?.get(n.id);
        if (out !== undefined) sampleOutputs[n.id] = out;
    }
    if (workflowVariables && Object.keys(workflowVariables).length > 0) {
        sampleOutputs.vars = workflowVariables;
    }
    const workflowNodes = inputNodes.map((n) => ({ id: n.id, data: { label: n.data?.label } }));
    const primaryInput = inputNodes.length === 1 ? sampleOutputs[inputNodes[0].id] : undefined;
    return { sampleOutputs, workflowNodes, primaryInput };
}

export function useExpressionPreview(expression: string): ExpressionPreviewState {
    const ctx = useReferenceAutocomplete();
    const [state, setState] = useState<ExpressionPreviewState>({ loading: false, hasResult: false });
    // Bump on every request so a slow earlier response can't overwrite a newer one.
    const reqRef = useRef(0);

    useEffect(() => {
        const expr = expression.trim();
        if (!expr) {
            setState({ loading: false, hasResult: false });
            return;
        }
        setState((s) => ({ ...s, loading: true }));
        const myReq = ++reqRef.current;
        const timer = setTimeout(async () => {
            const { sampleOutputs, workflowNodes, primaryInput } = buildSampleOutputs(
                ctx?.inputNodes ?? [],
                ctx?.workflowVariables,
                ctx?.expectedSchemas,
            );
            try {
                const resp = (await sendEventAsync(
                    WorkflowNodeEvaluateExpressionRequest.create({
                        expression: expr,
                        sample_outputs: sampleOutputs,
                        workflow_nodes: workflowNodes,
                        primary_input: primaryInput,
                    }),
                    undefined,
                    8000,
                )) as { ok?: boolean; kind?: string; keys?: string[] | null; preview?: string; preview_tokens?: Array<{ t: string; v: string }>; error?: string };
                if (myReq !== reqRef.current) return; // superseded
                if (resp?.error || resp?.ok === false) {
                    setState({ loading: false, hasResult: true, error: resp.error || 'Evaluation failed' });
                } else {
                    setState({ loading: false, hasResult: true, kind: resp.kind, keys: resp.keys, preview: resp.preview, previewTokens: resp.preview_tokens });
                }
            } catch (e) {
                if (myReq !== reqRef.current) return;
                setState({ loading: false, hasResult: true, error: e instanceof Error ? e.message : 'Request failed' });
            }
        }, DEBOUNCE_MS);

        return () => clearTimeout(timer);
    }, [expression, ctx?.inputNodes, ctx?.workflowVariables, ctx?.expectedSchemas]);

    return state;
}
