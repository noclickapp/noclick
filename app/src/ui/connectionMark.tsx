// A connection's, an integration's or an account's mark and name, as whoever renders the app draws them (the
// `connection.mark` slot).
import { standing, useSlot } from '@/slots';
import type { MarkSize } from './primitives';
import { CONNECTION_MARK, type ConnectionMarks } from './slots';

export function CredentialMark(props: { credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }) {
    const { Mark } = useSlot(CONNECTION_MARK);
    return <Mark {...props} />;
}

/** What the service is called. Read as the row draws (a table's cell is no place for a hook). */
export function credentialLabel(credentialType: string, nodeType?: string | null): string {
    return standing(CONNECTION_MARK).label(credentialType, nodeType);
}

/** The marks and glyphs accounts wear, for a component that draws several. */
export function useConnectionMarks(): ConnectionMarks {
    return useSlot(CONNECTION_MARK);
}
