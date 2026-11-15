// The connect flow's stages and the header each one reads under, apart from the flow itself so a dialog can word
// its header before the flow (and the node schemas it reads) has loaded.
import type { CredentialMethodKind } from '~/lib/credentialMethodKind';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';

export type ConnectStage = 'connect' | 'ask' | 'done';

/** What landed: what the connect-time check proved, and the account it landed on. */
export interface ConnectResult {
    kind: CredentialMethodKind;
    credentialType?: string;
    credentialId?: string;
    verification?: CredentialTestConnectionResponse | null;
    account?: string;
}

// Ways in whose landing the provider itself completed: a sign-in, or a scan it linked.
const PROVIDER_COMPLETED = new Set<CredentialMethodKind>(['oauth', 'agent_oauth', 'mcp', 'qr_scan']);

/** What a landing proved: the connect-time check's answer, or, where nothing asks the provider afterwards (a provide
 *  link hands over no verification at all), the provider completing a sign-in or scan, as the provide page reads it.
 *  A key nothing vouched for stays saved, not verified. */
export function landedVerification(result: ConnectResult): CredentialTestConnectionResponse | null | undefined {
    return result.verification === undefined && PROVIDER_COMPLETED.has(result.kind) ? { reachable: true } : result.verification;
}

/** A dialog's title and line for each stage, so every host words it the same. */
export function connectDialogHeader(app: string, stage: ConnectStage, result?: ConnectResult): { title: string; description?: string } {
    if (stage === 'ask') return { title: `Ask someone to connect ${app}`, description: 'For an account that isn’t yours. They connect it from a link.' };
    if (stage === 'done') {
        // Connected takes proof: the provider answering, or a sign-in it didn't refuse. A key nothing vouched for is saved.
        const verification = result && landedVerification(result);
        const signedIn = (result?.kind === 'oauth' || result?.kind === 'agent_oauth' || result?.kind === 'mcp') && verification?.reachable !== false;
        return { title: verification?.reachable === true || signedIn ? `${app} is connected` : `${app} is saved` };
    }
    return { title: `Connect ${app}`, description: `So NoClick can work in ${app} for you.` };
}
