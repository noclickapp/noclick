// What an agent can run on, read once for every Work view that picks it: the harnesses (GET /v1/harnesses, with each
// one's efforts, speeds and whether NoClick's key runs it), their models, and the AI accounts the account holds (its
// model connections). Cached per client; a connect elsewhere reads the accounts again with `rereadAccounts`, and so
// does the backend's frame when a connection's sign-in lands or its link lapses.
import { useMemo } from 'react';
import { Lock, PenLine, ShieldOff, Sparkles, type LucideIcon } from 'lucide-react';
import { Agent, Connection, type HarnessInfo, type HarnessModel, type HarnessName, type PermissionMode } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';
import { accountsOf, type ModelAccount } from './accounts';

export function useHarnesses() {
    return useWorkV1('work:harnesses', (client) => Agent.harnesses({ client }));
}

/** A harness's models, its default first: the first page, or those matching `search`. */
export function useHarnessModels(harness: HarnessInfo | undefined, search = '') {
    return useWorkV1(harness ? `work:models:${harness.name}:${search.trim().toLowerCase()}` : null, () => harness!.models({ search: search.trim() || undefined, limit: 50 }));
}

/** The ways to a pick's model (each id that runs it, the pick's own first), read from its harness's list by the model
 *  they share (`canonical`); on OpenCode, a free model of Zen's own tier among them, which runs with no account; and
 *  the funds the pick's own model needs on NoClick's key (`needsFunds`: a costly one's, else null). */
export function useModelRoutes(harness: HarnessInfo | undefined, model: string): { routes: string[]; free: { id: string; name: string } | null; needsFunds: number | null; outputUsdPerMillion: number | null } {
    // Its name without its version's last part finds every spelling of it ("claude-sonnet-5.5", "claude-sonnet-5-5").
    const term = (model.split('/').at(-1) ?? model).replace(/[-.]\d+$/, '');
    const found = useWorkV1(harness && model ? `work:routes:${harness.name}:${model}` : null, () => harness!.models({ search: term, limit: 50 }));
    return useMemo(() => {
        const rows = found.data ?? [];
        const own = rows.find((m) => m.id === model);
        const same = own ? rows.filter((m) => m.canonical === own.canonical) : [];
        const zen = harness?.name === 'opencode' ? same.find((m) => m.route === 'opencode' && modelParts(m.label, m.id).free) : undefined;
        return {
            routes: [model, ...same.map((m) => m.id).filter((id) => id !== model)],
            free: zen ? { id: zen.id, name: modelParts(zen.label, zen.id).name } : null,
            needsFunds: own?.noclickKey?.needsFundsUsd ?? null,
            outputUsdPerMillion: own?.noclickKey?.outputUsdPerMillion ?? null,
        };
    }, [found.data, model, harness?.name]);
}

/** A search over every harness's models at once. */
export function useModelSearch(harnesses: readonly HarnessInfo[] | undefined, search: string) {
    const q = search.trim().toLowerCase();
    return useWorkV1(harnesses && q ? `work:models:search:${q}` : null, async () => {
        const lists = await Promise.all(harnesses!.map(async (h) => (await h.models({ search: q, limit: 20 })).map((m) => ({ harness: h.name, model: m }))));
        return lists.flat();
    });
}

const CONNECTIONS_KEY = 'work:connections';

/** The account's connections, read again whenever one moves (a sign-in landing, a link lapsing, one removed). */
export function useConnections() {
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'connection') rereadAccounts();
    });
    return useWorkV1(CONNECTIONS_KEY, (client) => Connection.list({ client }));
}

/** The model connections the account holds, as accounts, with the model providers' names and labels. */
export function useModelAccounts(): { accounts: ModelAccount[] | undefined; labels: ReadonlyMap<string, string>; error: unknown } {
    const connections = useConnections();
    const providers = useWorkV1('work:integrations:model', (client) => Connection.integrations(undefined, { client, kind: 'model' }));
    return useMemo(() => {
        const labels = new Map((providers.data ?? []).map((i) => [i.name, i.label ?? i.name]));
        const names = new Set(labels.keys());
        return {
            accounts: connections.data && providers.data ? accountsOf(connections.data, names, labels) : undefined,
            labels,
            error: connections.error ?? providers.error,
        };
    }, [connections.data, connections.error, providers.data, providers.error]);
}

export const rereadAccounts = () => invalidateV1(CONNECTIONS_KEY);

// ── a harness's own traits ──────────────────────────────────────────────────

/** How a harness names its reasoning knob, as its own UI does. */
const EFFORT_LABEL: Record<HarnessName, string> = { claude_code: 'Effort', codex: 'Reasoning', opencode: 'Variant', hermes: 'Reasoning', openclaw: 'Thinking', sdk: 'Thinking' };

/** Its effort levels (weakest first), the default, and its speeds (none where it has no fast mode). */
export function traitsOf(harness: HarnessInfo): { label: string; efforts: string[]; defaultEffort: string | null; speeds: string[] } {
    return { label: EFFORT_LABEL[harness.name] ?? 'Effort', efforts: harness.efforts, defaultEffort: harness.defaultEffort ?? harness.efforts[0] ?? null, speeds: harness.speeds };
}

/** When it asks before acting, as t3code's modes. */
export const PERMISSION_MODES: { id: PermissionMode; label: string; note: string }[] = [
    { id: 'approval-required', label: 'Supervised', note: 'Asks before commands and file changes' },
    { id: 'auto-accept-edits', label: 'Auto-accept edits', note: 'Edits files freely; asks before other actions' },
    { id: 'auto', label: 'Auto', note: 'Its own review approves routine actions and asks about the rest' },
    { id: 'full-access', label: 'Full access', note: 'Commands and edits without asking' },
];

/** Each permission mode's icon, as t3code draws them. */
export const PERMISSION_ICON: Record<PermissionMode, LucideIcon> = { 'approval-required': Lock, 'auto-accept-edits': PenLine, auto: Sparkles, 'full-access': ShieldOff };

/** The modes a harness takes (or `only`, a conversation's), each noted in the harness's own words where it runs one as
 *  another; and its note when every mode runs the same. */
export function modesOf(harness: HarnessInfo | undefined, only?: readonly PermissionMode[]): { modes: typeof PERMISSION_MODES; note: string | null } {
    const offered = only ?? harness?.permissionModes ?? [];
    const notes = harness?.notSupported ?? {};
    return {
        modes: PERMISSION_MODES.filter((m) => offered.includes(m.id)).map((m) => ({ ...m, note: notes[m.id] ?? m.note })),
        note: notes.modes ?? null,
    };
}

/** A model as Work names it, from its harness's label ("[openrouter] OpenAI: GPT-6 Luna (latest)"): its plain name
 *  ("GPT-6 Luna", without the route in brackets, the maker before a colon, "latest", the context size or plan badges), the route
 *  it's reached through ("openrouter"), whether it's free, and whether it's an alias that always takes the newest
 *  (its id's `~`, or "latest" on its label); its id's last part until its list is read. */
export function modelParts(label: string | null | undefined, id: string): { name: string; via: string | null; free: boolean; latest: boolean } {
    const text = (label ?? '').split(' · ')[0].trim();
    const via = /^\[([^\]]+)\]/.exec(text)?.[1] ?? null;
    const [head, ...notes] = text.replace(/^\[[^\]]*\]\s*/, '').split(' - ');
    const bare = head.replace(/^[^:]{1,30}:\s+/, '');
    const name = bare.replace(/\s*\(?latest\)?$/i, '').trim();
    return { name: name || idName(id), via, free: notes.some((n) => n.trim() === 'Free'), latest: id.includes('~') || name !== bare.trim() };
}

const ACRONYMS = new Set(['gpt', 'glm', 'oss', 'vl', 'ai', 'llm']);

/** A model's id read as a name, for one no list has named yet: `claude-opus-5-5` is Claude Opus 5.5, `gpt-5.5`
 *  GPT-5.5, a dated snapshot without its date. */
export function idName(id: string): string {
    const last = (id.split('/').at(-1) ?? id).replace(/^~/, '').replace(/:.*$/, '').replace(/-(\d{8}|\d{4}-\d{2}-\d{2})$/, '');
    const words: string[] = [];
    for (const part of last.split(/[-_\s]+/).filter(Boolean)) {
        const before = words.at(-1);
        // A version's parts written apart (`5-5`) are one version (5.5).
        if (/^\d{1,2}$/.test(part) && before && /^\d{1,2}(\.\d{1,2})*$/.test(before)) words[words.length - 1] = `${before}.${part}`;
        else words.push(part);
    }
    const name = words.map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1))).join(' ');
    return name.replace(/^GPT (\d)/, 'GPT-$1') || id;
}

/** The row of a harness's list that is `id`: by its own id, else the alias running it (Claude Code lists `opus`; an
 *  agent set through the API holds `claude-opus-5-5`, which the alias's `canonical` names). */
export function listedModel<T extends { id: string; canonical?: string | null }>(rows: readonly T[] | undefined, id: string): T | undefined {
    return rows?.find((m) => m.id === id) ?? rows?.find((m) => m.canonical === id);
}

/** `id`'s row in `harness`'s list: its first page, else a search by the id (a long list's model past that page, or
 *  one the list names by an alias). */
export function useListedModel(harness: HarnessInfo | undefined, id: string): HarnessModel | undefined {
    const first = useHarnessModels(harness);
    const onPage = listedModel(first.data, id);
    const searched = useHarnessModels(first.data && !onPage && id ? harness : undefined, id);
    return onPage ?? listedModel(searched.data, id);
}

/** A model as a picker lists it. */
export interface ModelRow {
    harness: HarnessName;
    model: string;
    label: string;
    /** The model it reaches, as its maker names it: rows reaching one model are one row. */
    canonical?: string;
    /** Said quietly after it: Latest on an alias beside the model it names, the route where another model shares its
     *  name, and Free. */
    note?: string;
    /** The funds the account must have added to put an agent on it on NoClick's key (a costly model); null otherwise. */
    needsFunds?: number | null;
    /** Its output a million tokens on NoClick's key (null for a router priced as the model it picks). */
    outputUsdPerMillion?: number | null;
}

/** Rows by their plain names, one per model however many ways reach it (the first way listed stands for it; the
 *  account picks the way). An alias that always takes the newest says Latest where the list also has the model it
 *  names (alone, as in Claude Code's list of aliases, it's just its name); a row says its route where another model
 *  shares its name; a free one says Free. */
export function namedRows<T>(items: readonly T[], row: (item: T) => ModelRow): ModelRow[] {
    const seen = new Set<string>();
    const rows = items
        .map((item) => row(item))
        .filter((r) => {
            const key = `${r.harness}:${r.canonical ?? r.model}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        })
        .map((r) => ({ r, parts: modelParts(r.label, r.model) }));
    const count = (harness: string, name: string, latest: boolean) => rows.filter(({ r, parts }) => r.harness === harness && parts.name === name && parts.latest === latest).length;
    return rows.map(({ r, parts }) => {
        const beside = parts.latest && count(r.harness, parts.name, false) > 0;
        const shared = count(r.harness, parts.name, parts.latest) > 1;
        const note = [beside ? 'Latest' : null, shared ? parts.via : null, parts.free ? 'Free' : null].filter(Boolean).join(' · ');
        return { ...r, label: parts.name, ...(note ? { note } : {}) };
    });
}

export const modelName = (label: string | null | undefined, id: string) => modelParts(label, id).name;

export type { HarnessModel };
