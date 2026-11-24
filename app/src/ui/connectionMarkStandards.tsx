// What stands in the `connection.mark` slot (slots.ts) when no host fills it.
import { Plug } from 'lucide-react';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { NodeMark, nodeLabel, type MarkSize } from './primitives';
import { addedLabel } from '@/lib/formatters';
import type { AccountFacts, AccountNames, Glyph } from './slots';

/** The mark the icon registry holds for the service's node type: a plain cube when it holds none. */
export function StandardCredentialMark({ nodeType, size = 'sm', className }: { credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }) {
    return <NodeMark type={nodeType ?? ''} size={size} className={className} />;
}

/** The service's name as the icon registry has it, else read off its type: `automation-google-sheets` is
 *  "Google sheets". */
export function standardCredentialLabel(credentialType: string, nodeType?: string | null): string {
    if (nodeType && getNodeIconMeta(nodeType)) return nodeLabel(nodeType);
    const words = (nodeType || credentialType).replace(/^automation-/, '').replace(/[-_]+/g, ' ').trim();
    return words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
}

/** A plug in the ink around it, for any account. */
export const plainGlyph = (): Glyph => ({ Icon: Plug, iconColor: 'text-muted-foreground' });

/** An account named after its integration (what the app keeps that is no app's account, after its kind): the account
 *  it reaches, else the name it was given where that isn't its app's, else when it was connected. */
export function standardAccountNames({ credentialType, integration, name, account, connectedAt }: AccountFacts): AccountNames {
    const app = standardCredentialLabel(credentialType, integration ? `automation-${integration.replace(/_/g, '-')}` : null);
    const own = name.trim();
    const line = account ?? (own && own.toLowerCase() !== app.toLowerCase() ? own : connectedAt ? addedLabel(connectedAt) : app);
    return { app, line, aliases: [] };
}
