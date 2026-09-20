// Load memory headers separately from their full content and route edits through
// the account coordinator's authenticated socket API. Request generations keep
// a slower search or selection from replacing the user's newer view.
import { useCallback, useEffect, useRef, useState } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    CoordinatorMemoriesListRequest,
    CoordinatorMemoryDeleteRequest,
    CoordinatorMemoryGetRequest,
    CoordinatorMemorySaveRequest,
    type CoordinatorMemoryWrite,
} from '~/types/socket-events.generated';

export type MemoryHeader = {
    id: string;
    name: string;
    description: string;
    memory_type: CoordinatorMemoryWrite['memory_type'];
    origin_conversation_id: string | null;
    version: number;
    created_at: string;
    updated_at: string;
};
export type MemoryEntry = MemoryHeader & { content: string };
export type MemoryPage = { memories: MemoryHeader[]; has_more: boolean };
export type MemoryTransport = {
    list: (query: string, offset: number) => Promise<MemoryPage>;
    get: (id: string) => Promise<MemoryEntry>;
    save: (memory: CoordinatorMemoryWrite) => Promise<MemoryEntry>;
    forget: (id: string, version: number) => Promise<void>;
};

async function reply<T>(pending: Promise<T & { error?: string }>): Promise<T> {
    const result = await pending;
    if (result.error) throw new Error(result.error);
    return result;
}

export const coordinatorMemoryTransport: MemoryTransport = {
    list: (query, offset) =>
        reply(
            sendEventAsync<MemoryPage>(
                CoordinatorMemoriesListRequest.create({
                    request_id: crypto.randomUUID(),
                    query,
                    offset,
                })
            )
        ),
    get: async (memory_id) =>
        (
            await reply(
                sendEventAsync<{ memory: MemoryEntry }>(
                    CoordinatorMemoryGetRequest.create({
                        request_id: crypto.randomUUID(),
                        memory_id,
                    })
                )
            )
        ).memory,
    save: async (memory) =>
        (
            await reply(
                sendEventAsync<{ memory: MemoryEntry }>(
                    CoordinatorMemorySaveRequest.create({
                        request_id: crypto.randomUUID(),
                        memory,
                    })
                )
            )
        ).memory,
    forget: async (memory_id, expected_version) => {
        await reply(
            sendEventAsync<{ deleted: boolean }>(
                CoordinatorMemoryDeleteRequest.create({
                    request_id: crypto.randomUUID(),
                    memory_id,
                    expected_version,
                })
            )
        );
    },
};

const message = (error: unknown) =>
    error instanceof Error ? error.message : 'Could not load memories';

export function useCoordinatorMemories(
    transport: MemoryTransport = coordinatorMemoryTransport,
    enabled = true
) {
    const [query, setQuery] = useState('');
    const [offset, setOffset] = useState(0);
    const [revision, refresh] = useState(0);
    const [page, setPage] = useState<MemoryPage>({
        memories: [],
        has_more: false,
    });
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [listError, setListError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [editorRevision, setEditorRevision] = useState(0);
    const [selected, setSelected] = useState<MemoryEntry | 'new' | null>(null);
    const selection = useRef(0);

    useEffect(() => {
        if (!enabled) return;
        let cancelled = false;
        setLoading(true);
        const timer = setTimeout(() => {
            transport
                .list(query, offset)
                .then((result) => {
                    if (!cancelled) {
                        setPage(result);
                        setListError(null);
                    }
                })
                .catch((cause: unknown) => {
                    if (!cancelled) {
                        setPage({ memories: [], has_more: false });
                        setListError(message(cause));
                    }
                })
                .finally(() => {
                    if (!cancelled) setLoading(false);
                });
        }, 150);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [query, offset, revision, transport, enabled]);

    useEffect(
        () => () => {
            selection.current += 1;
        },
        []
    );

    const select = useCallback(
        async (id: string) => {
            const generation = ++selection.current;
            setBusy(true);
            setError(null);
            setNotice(null);
            try {
                const entry = await transport.get(id);
                if (generation === selection.current) {
                    setSelected(entry);
                    setEditorRevision((value) => value + 1);
                }
            } catch (cause) {
                if (generation === selection.current) setError(message(cause));
            } finally {
                if (generation === selection.current) setBusy(false);
            }
        },
        [transport]
    );

    const save = async (input: CoordinatorMemoryWrite) => {
        setBusy(true);
        setError(null);
        setNotice(null);
        try {
            setSelected(await transport.save(input));
            setEditorRevision((value) => value + 1);
            setNotice('Memory saved');
            refresh((value) => value + 1);
        } catch (cause) {
            setError(message(cause));
        } finally {
            setBusy(false);
        }
    };

    const forget = async (entry: MemoryEntry) => {
        setBusy(true);
        setError(null);
        setNotice(null);
        try {
            await transport.forget(entry.id, entry.version);
            setSelected(null);
            setNotice('Memory forgotten');
            setOffset(0);
            refresh((value) => value + 1);
        } catch (cause) {
            setError(message(cause));
        } finally {
            setBusy(false);
        }
    };

    const search = useCallback((value: string) => {
        setQuery(value);
        setOffset(0);
    }, []);
    const back = useCallback(() => {
        selection.current += 1;
        setBusy(false);
        setSelected(null);
        setError(null);
        setNotice(null);
    }, []);
    const create = useCallback(() => {
        selection.current += 1;
        setBusy(false);
        setSelected('new');
        setError(null);
        setNotice(null);
    }, []);

    return {
        ...page,
        query,
        offset,
        loading,
        busy,
        error: error || (!selected ? listError : null),
        notice,
        editorRevision,
        selected,
        select,
        save,
        forget,
        search,
        setOffset,
        reload: () => refresh((value) => value + 1),
        back,
        create,
    };
}

export type CoordinatorMemoryState = ReturnType<typeof useCoordinatorMemories>;
