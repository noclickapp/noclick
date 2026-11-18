// A connection's or an integration's mark and name, as whoever renders the console draws them (the
// `console.connection.mark` slot).
import { standing, useSlot } from '@/slots';
import type { MarkSize } from '@/ui/primitives';
import { CONNECTION_MARK } from './slots';

export function CredentialMark(props: { credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }) {
    const { Mark } = useSlot(CONNECTION_MARK);
    return <Mark {...props} />;
}

/** What the service is called. Read as the row draws (a table's cell is no place for a hook). */
export function credentialLabel(credentialType: string, nodeType?: string | null): string {
    return standing(CONNECTION_MARK).label(credentialType, nodeType);
}
