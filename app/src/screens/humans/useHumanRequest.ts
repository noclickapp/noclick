// A question an agent asked the account's owner (human__ask), as its card in a chat shows it, or a call held for
// their yes: read and answered through the request's own routes (GET /v1/humans/requests/{id}, POST .../answer) with
// the page's client, the same answer the request's page and texts give. Read again when the tab comes back into focus
// while it waits: it may have been answered from a text or the page meanwhile.
import { useCallback, useEffect, useState } from 'react';
import type { NoClick } from 'noclick';

/** A question about something in a connected account: the field its choices come from, and the account's
 *  connection that lists them (the picker the canvas's questions use). */
export interface OwnerPick {
    integration: string;
    field: string;
    field_label: string;
    node_type: string;
    field_schema: Record<string, unknown> | null;
    credential: { id: string; type: string };
    arguments: Record<string, unknown>;
}

/** The request as `/v1/humans/requests/{id}` answers it (the fields the card reads). */
export interface OwnerQuestion {
    id: string;
    status: 'pending' | 'answered' | 'expired' | 'canceled' | string;
    message: string;
    options: string[] | null;
    pick?: OwnerPick | null;
    /** An approval's answer carries `approved`. */
    answer: { choice?: string | null; value?: string | null; text?: string | null; approved?: boolean | null } | null;
    /** `account`: the account held only one, so it answered and nobody was asked. */
    answered_by?: string | null;
    expires_at: string | null;
    owner_can_answer?: boolean;
}

/** A question's answer (`choice` or `text`), or an approval's (`approved`, with an optional `note`). */
export interface OwnerAnswer {
    choice?: string;
    text?: string;
    approved?: boolean;
    note?: string | null;
}

function messageOf(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}

/** The request `requestId`, read and answered with `client` (the page's own). */
export function useHumanRequest(client: NoClick, requestId: string) {
    const path = `/v1/humans/requests/${encodeURIComponent(requestId)}`;
    const [question, setQuestion] = useState<OwnerQuestion | null>(null);
    const [unreadable, setUnreadable] = useState(false);
    const [answering, setAnswering] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setQuestion(await client.request<OwnerQuestion>('GET', path, { user: null }));
            setUnreadable(false);
        } catch (error) {
            console.warn('[coordinator] reading the question failed:', error);
            setUnreadable(true);
        }
    }, [client, path]);

    useEffect(() => {
        void load();
    }, [load]);

    const waiting = !question || question.status === 'pending';
    useEffect(() => {
        if (!waiting) return;
        const look = () => void load();
        window.addEventListener('focus', look);
        return () => window.removeEventListener('focus', look);
    }, [waiting, load]);

    const answer = useCallback(
        async (given: OwnerAnswer) => {
            setAnswering(true);
            setFailure(null);
            try {
                setQuestion(await client.request<OwnerQuestion>('POST', `${path}/answer`, { json: given, user: null }));
            } catch (error) {
                setFailure(messageOf(error));
                void load();
            } finally {
                setAnswering(false);
            }
        },
        [client, path, load]
    );

    return { question, unreadable, answering, failure, answer };
}
