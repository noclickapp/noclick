// Copy-link button rendered in the header of a form block (interface-form) — the
// unified form node's public URL affordance, styled like InterfaceNodePublishButton
// so desktop (xyflow) canvas and mobile ForkCanvas share one component. The link is
// always-on: it reads config.webhook_url when the config panel already minted it,
// else mints on demand via workflow:node:load_value (idempotent per workflow+node).

import { useRef, useState } from 'react';
import { Check, Link } from 'lucide-react';
import { resolveNodeType } from '~/utils/nodeSchemas';
import { sendEventAsync } from '~/lib/socket-sender';
import type { BlockConfig } from '~/components/interface/types';

interface InterfaceFormLinkButtonProps {
    nodeId: string;
    nodeType: string | undefined;
    config: BlockConfig;
    workflowId: string | undefined;
    isReadOnly?: boolean;
}

export function InterfaceFormLinkButton({
    nodeId,
    nodeType,
    config,
    workflowId,
    isReadOnly,
}: InterfaceFormLinkButtonProps) {
    const [copied, setCopied] = useState(false);
    const [loading, setLoading] = useState(false);
    // Cache the minted URL so repeat copies skip the round-trip; config.webhook_url
    // wins when present (the config panel's loadValue populates it on open).
    const mintedUrlRef = useRef<string | null>(null);

    const show =
        !!workflowId && !isReadOnly && !!nodeType && resolveNodeType(nodeType) === 'interface-form';
    if (!show) return null;

    const configUrl = typeof config.webhook_url === 'string' ? config.webhook_url : '';

    const handleCopy = async (e: React.MouseEvent) => {
        e.stopPropagation();
        if (loading) return;
        let url = configUrl.startsWith('http') ? configUrl : mintedUrlRef.current;
        if (!url) {
            setLoading(true);
            try {
                const response = (await sendEventAsync({
                    event_name: 'workflow:node:load_value',
                    node_type: 'interface-form',
                    field_name: 'webhook_url',
                    workflow_id: workflowId,
                    node_id: nodeId,
                    context: config,
                } as never)) as { success?: boolean; value?: unknown; values?: Record<string, unknown> };
                const minted = response?.values?.webhook_url ?? response?.value;
                if (typeof minted === 'string' && minted.startsWith('http')) {
                    mintedUrlRef.current = minted;
                    url = minted;
                }
            } catch (error) {
                console.error('[InterfaceFormLinkButton] Failed to mint form link:', error);
            } finally {
                setLoading(false);
            }
        }
        if (!url) return;
        try {
            await navigator.clipboard.writeText(url);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
        } catch (error) {
            console.error('[InterfaceFormLinkButton] Clipboard write failed:', error);
        }
    };

    return (
        <button
            type="button"
            onClick={handleCopy}
            className="nodrag flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-full bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm transition-all disabled:opacity-60"
            disabled={loading}
            title="Copy the public form link — anyone with it can submit this form"
        >
            {copied ? <Check className="w-4 h-4" /> : <Link className="w-4 h-4" />}
            {copied ? 'Copied' : loading ? 'Getting link…' : 'Copy link'}
        </button>
    );
}
