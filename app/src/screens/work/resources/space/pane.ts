// What every part of a space's Resources tab is handed: where it is, what the space has, and the ways out of a row.
import type { Connection, NoClick } from 'noclick';
import type { KindId } from '@/screens/resources/kinds';
import type { SpaceKind, SpaceShare, Thing } from './data';

/** Where the tab is: its overview (null), one kind's list, or one item's page. */
export type SpaceAt = { kind: SpaceKind; item?: string } | null;

export type Dialog = { kind: 'create'; of: SpaceKind } | { kind: 'add'; of: SpaceKind } | { kind: 'delete'; key: string } | { kind: 'share'; key: string } | null;

export interface Pane {
    spaceId: string;
    share: SpaceShare;
    /** The account's connections, by id and by ref (a space names one either way): a named one also by its name, an
     *  account connected in the app never by its name. */
    connections: ReadonlyMap<string, Connection>;
    now: string;
    onAt(at: SpaceAt): void;
    /** Its page: an agent's is its profile, the rest open in the tab. */
    open(t: Thing): void;
    ask(dialog: Dialog): void;
    rename(client: NoClick, t: Thing, name: string): Promise<void>;
    /** The account's Resources page: a kind's list, or one of its items; absent where the app has no such page. */
    accountPage?(kind: KindId | null, resource?: string): void;
}

/** The account's Resources kind each of a space's kinds is listed under (agents, connections and channels live elsewhere). */
export const ACCOUNT_KIND: Partial<Record<SpaceKind, KindId>> = {
    machines: 'machines',
    skills: 'skills',
    memories: 'memories',
    code: 'repos',
    websites: 'apps',
    databases: 'databases',
    files: 'storage',
    numbers: 'numbers',
    email: 'email',
    secrets: 'secrets',
};
