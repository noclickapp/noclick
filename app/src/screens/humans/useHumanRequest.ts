// A question an agent asked the account's owner (human__ask), as its card in a chat shows it, or a call held for
// their yes: read and answered through the request's own routes (GET /v1/humans/requests/{id}, POST .../answer) with
// the page's client, the same answer the request's page and texts give. Read again when the tab comes back into focus
// while it waits: it may have been answered from a text or the page meanwhile.
import { useCallback, useEffect, useRef, useState } from 'react';
import { HumanRequest, type NoClick } from 'noclick';

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

/** A workflow step a question fills in. */
export interface QuestionStep {
    workflow_id: string;
    workflow_name?: string | null;
    step_id: string;
    step_name?: string | null;
}

/** One of the account's connections a connect question's step could take. */
export interface StepChoice {
    ref: string;
    name: string;
    account?: string | null;
    integration?: string | null;
    credential_type?: string | null;
}

/** Which of the account's connections a workflow step uses: `choices` as the signed-in owner reads them. */
export interface ConnectQuestion {
    integration: string;
    label: string;
    credential_types: string[];
    slot?: string | null;
    step: QuestionStep;
    choices?: StepChoice[];
}

/** The values of a secret, kept as the account's secret and, with `step`, given to an agent step's shell. */
export interface SecretQuestion {
    name: string;
    keys: string[];
    step?: QuestionStep | null;
}

/** A file in the asking agent's sandbox or machine its owner fills in: a value for each of `keys` (set in it as
 *  `KEY=value` lines), else the whole file. */
export interface FileQuestion {
    path: string;
    keys: string[] | null;
    agent_id: string;
    agent_name?: string | null;
}

/** The request as `/v1/humans/requests/{id}` answers it (the fields the card reads). */
export interface OwnerQuestion {
    id: string;
    status: 'pending' | 'answered' | 'expired' | 'canceled' | string;
    message: string;
    options: string[] | null;
    pick?: OwnerPick | null;
    multiple?: boolean;
    connect?: ConnectQuestion | null;
    secret?: SecretQuestion | null;
    file?: FileQuestion | null;
    /** Its page: the owner's own link, for the signed-in owner. */
    url?: string | null;
    /** An approval's answer carries `approved`; a connect question's `connection` and `account`; a secret's `secret`;
     *  a file's where it went and its key names (never a value). */
    answer: {
        choice?: string | null;
        choices?: string[] | null;
        value?: string | null;
        text?: string | null;
        approved?: boolean | null;
        connection?: string | null;
        account?: string | null;
        secret?: string | null;
        path?: string | null;
        keys?: string[] | null;
    } | null;
    /** `account`: the account held only one, so it answered and nobody was asked. */
    answered_by?: string | null;
    expires_at: string | null;
    owner_can_answer?: boolean;
}

/** A question's answer (`choice` or `text`), an approval's (`approved`, with an optional `note`), a connect
 *  question's (`connection`: a connection's ref), a secret's or a file's keys (`secret_values`, never shown again), or
 *  a file's whole text (`file_content`, never shown again). */
export interface OwnerAnswer {
    choice?: string;
    text?: string;
    approved?: boolean;
    note?: string | null;
    connection?: string;
    secret_values?: Record<string, string>;
    file_content?: string;
}

function messageOf(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}

/** The request `requestId`, read and answered with `client` (the page's own). */
export function useHumanRequest(client: NoClick, requestId: string) {
    // The request as last read, which an answer goes through.
    const held = useRef<HumanRequest<unknown> | null>(null);
    const [question, setQuestion] = useState<OwnerQuestion | null>(null);
    const [unreadable, setUnreadable] = useState(false);
    const [answering, setAnswering] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            held.current = await HumanRequest.retrieve(requestId, { client, user: null });
            setQuestion(held.current.request as unknown as OwnerQuestion);
            setUnreadable(false);
        } catch (error) {
            console.warn('[coordinator] reading the question failed:', error);
            setUnreadable(true);
        }
    }, [client, requestId]);

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
                const request = held.current ?? (await HumanRequest.retrieve(requestId, { client, user: null }));
                const note = given.note ?? undefined;
                if (given.approved !== undefined) await (given.approved ? request.approve({ note }) : request.decline({ note }));
                else await request.answer({ choice: given.choice, text: given.text, connection: given.connection, secretValues: given.secret_values, fileContent: given.file_content });
                held.current = request;
                setQuestion(request.request as unknown as OwnerQuestion);
            } catch (error) {
                setFailure(messageOf(error));
                void load();
            } finally {
                setAnswering(false);
            }
        },
        [client, requestId, load]
    );

    return { question, unreadable, answering, failure, answer };
}
