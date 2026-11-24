// The memory panel's state: memory headers read apart from their full content, edits through the chat's transport (its
// agent's memory on the platform API, or another chat's own). Request generations keep a slower search or selection
// from replacing the user's newer view.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useReportHeld } from '@/sdk/held';

/** A memory as the panel writes it: a new one, or a change to `memory_id` at the version it read. */
export interface MemoryWrite {
    name: string;
    description: string;
    memory_type: 'user' | 'feedback' | 'project' | 'reference';
    content: string;
    memory_id?: string | null;
    expected_version?: number | null;
}

export type MemoryHeader = {
    id: string;
    name: string;
    description: string;
    memory_type: MemoryWrite['memory_type'];
    origin_conversation_id: string | null;
    version: number;
    created_at: string;
    updated_at: string;
};
export type MemoryEntry = MemoryHeader & { content: string };
export type MemoryPage = { memories: MemoryHeader[]; has_more: boolean };
/** What a memory's name may be, as the editor's field checks it. */
export type MemoryNames = { pattern: string; maxLength: number; hint: string };
const HYPHENATED: MemoryNames = { pattern: '[a-z0-9]+(-[a-z0-9]+)*', maxLength: 100, hint: 'Lowercase words separated by hyphens' };
export type MemoryTransport = {
    list: (query: string, offset: number) => Promise<MemoryPage>;
    get: (id: string) => Promise<MemoryEntry>;
    save: (memory: MemoryWrite) => Promise<MemoryEntry>;
    forget: (id: string, version: number) => Promise<void>;
    /** False where memories have no kind (an agent's): the panel neither shows nor asks one. */
    kinds?: boolean;
    /** Where names aren't lowercase words joined by hyphens. */
    names?: MemoryNames;
};

const message = (error: unknown) =>
    error instanceof Error ? error.message : 'Could not load memories';

export function useMemories(transport: MemoryTransport, enabled = true) {
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
    // Forgetting can't be undone, so a key NoClick gave this app has it wait for the account's owner: a toast follows it.
    const reportHeld = useReportHeld();

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

    const save = async (input: MemoryWrite) => {
        setBusy(true);
        setError(null);
        setNotice(null);
        try {
            setSelected(await transport.save(input));
            setEditorRevision((value) => value + 1);
            setNotice('Memory saved');
            refresh((value) => value + 1);
        } catch (cause) {
            // Renamed: saved under its new name, and taking the old one away waits for the owner.
            if (reportHeld(cause, `Forget ${input.memory_id ?? input.name}`, () => refresh((value) => value + 1))) {
                refresh((value) => value + 1);
                return;
            }
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
            if (reportHeld(cause, `Forget ${entry.name}`, () => refresh((value) => value + 1))) return setSelected(null);
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
        kinds: transport.kinds !== false,
        names: transport.names ?? HYPHENATED,
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

export type MemoryState = ReturnType<typeof useMemories>;
