// The kinds of thing an account's agents and apps use, as Resources and the
// palette name them: plain names a developer already knows, one line on what
// each is, and how many the account has. Kept apart from the pages so the
// palette can list them without loading every kind's page.
import {
    AppWindow,
    Box,
    Braces,
    Compass,
    CreditCard,
    Database,
    FolderOpen,
    GitBranch,
    Globe,
    HardDrive,
    Inbox,
    ListOrdered,
    LockKeyhole,
    MessagesSquare,
    Phone,
    PlugZap,
    Server,
    type LucideIcon,
} from 'lucide-react';
import { formatCount } from '@/screens/console/lib/format';
import type { AccountView } from '@/sdk/owner';

/** The overview's order: a kind sits in one area, and the areas keep their order. */
export const AREAS = ['Accounts and channels', 'Running code', 'Data', 'Domains and money'] as const;
export type Area = (typeof AREAS)[number];

export type ResourceKindId =
    | 'connections'
    | 'phone'
    | 'inboxes'
    | 'channels'
    | 'sandboxes'
    | 'machines'
    | 'apps'
    | 'repos'
    | 'browser-profiles'
    | 'databases'
    | 'storage'
    | 'volumes'
    | 'dicts'
    | 'queues'
    | 'secrets'
    | 'domains'
    | 'cards';

export interface ResourceKind {
    id: ResourceKindId;
    area: Area;
    label: string;
    icon: LucideIcon;
    /** What it is, in one line: the overview's tile and the start of its page's lead. */
    what: string;
    /** What else its page's lead says: its limits and how it behaves. */
    note?: string;
    /** How many the account has, from the account; absent where the account doesn't count them (connections). */
    inUse?: (account: AccountView) => { count: number; line: string };
    /** Designed, not built yet: listed only in the lab, where its pages say so. */
    designed?: boolean;
}

export const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

const counted = (count: number | undefined, one: string, many?: string) => ({ count: count ?? 0, line: plural(count ?? 0, one, many) });

export const RESOURCE_KINDS: readonly ResourceKind[] = [
    {
        id: 'connections',
        area: 'Accounts and channels',
        label: 'Connections',
        icon: PlugZap,
        what: "Your users' Gmail, Slack, Stripe and more, which your code and agents act in.",
        note: 'Your code and agents use one by name, as the user it belongs to, and NoClick keeps its tokens fresh.',
    },
    {
        id: 'phone',
        area: 'Accounts and channels',
        label: 'Phone numbers',
        icon: Phone,
        what: 'Real numbers your agents answer and call from.',
        inUse: (a) => counted(a.counts.phone_numbers, 'number'),
    },
    {
        id: 'inboxes',
        area: 'Accounts and channels',
        label: 'Inboxes',
        icon: Inbox,
        what: 'Email addresses your code and agents receive mail at and reply from.',
        inUse: (a) => ({ count: a.counts.inboxes, line: `${formatCount(a.counts.inboxes)} of ${formatCount(a.limits.inboxes_max)} inboxes` }),
    },
    {
        id: 'channels',
        area: 'Accounts and channels',
        label: 'Channels',
        icon: MessagesSquare,
        what: 'Chat rooms where your agents, your users and other agents talk.',
        inUse: (a) => counted(a.counts.channels_open, 'open channel'),
    },
    {
        id: 'sandboxes',
        area: 'Running code',
        label: 'Sandboxes',
        icon: Box,
        what: 'Linux machines that run code for minutes or hours, billed by the second.',
        inUse: (a) => ({ count: a.counts.sandboxes_live, line: `${formatCount(a.counts.sandboxes_live)} of ${formatCount(a.limits.sandboxes_live_max)} running` }),
    },
    {
        id: 'machines',
        area: 'Running code',
        label: 'Machines',
        icon: Server,
        what: 'Always-on computers your agents run on, at a flat monthly price.',
        note: 'NoClick reviews each account before its first machine: ask here, saying what they will run.',
        inUse: (a) => counted(a.counts.machines, 'machine'),
    },
    {
        id: 'apps',
        area: 'Running code',
        label: 'Apps',
        icon: AppWindow,
        what: 'Repos deployed to a URL, with previews, domains and schedules.',
        note: 'Each app serves its main branch at its own URL and every other branch at a preview; an automation you publish is an app too.',
        inUse: (a) => counted(a.counts.apps, 'app'),
    },
    {
        id: 'repos',
        area: 'Running code',
        label: 'Repos',
        icon: GitBranch,
        what: 'Git repositories your code and agents commit to.',
        note: 'Your code commits through the API, and any git client clones or pushes with a short-lived URL.',
        inUse: (a) => counted(a.counts.repos, 'repo'),
    },
    {
        id: 'browser-profiles',
        area: 'Running code',
        label: 'Browser profiles',
        icon: Compass,
        what: 'Signed-in browsers your agents use on sites with no API.',
        inUse: (a) => counted(a.counts.browser_profiles, 'profile'),
    },
    {
        id: 'databases',
        area: 'Data',
        label: 'Databases',
        icon: Database,
        what: 'Postgres and SQLite databases your apps and agents keep their data in.',
        note: 'SQLite holds up to 10 GB, then move to Postgres. SQLite keeps 30 days of history to restore from, Postgres 7.',
        inUse: (a) => counted(a.counts.databases, 'database'),
    },
    {
        id: 'storage',
        area: 'Data',
        label: 'Storage',
        icon: HardDrive,
        what: 'Buckets of files, private by default, shared with signed links.',
        inUse: (a) => counted(a.counts.buckets, 'bucket'),
    },
    {
        id: 'volumes',
        area: 'Data',
        label: 'Volumes',
        icon: FolderOpen,
        what: 'Disks that keep files between runs, mounted into sandboxes and agents.',
        note: 'Up to 100 GB each; a sandbox or agent mounts up to 5.',
        inUse: (a) => counted(a.counts.volumes, 'volume'),
    },
    {
        id: 'dicts',
        area: 'Data',
        label: 'Key-value stores',
        icon: Braces,
        what: 'Small shared state by key, for your code and agents.',
        note: 'JSON values up to 1 MB each, and any key can expire. The SDK calls one a Dict.',
        inUse: (a) => counted(a.counts.dicts, 'store'),
    },
    {
        id: 'queues',
        area: 'Data',
        label: 'Queues',
        icon: ListOrdered,
        what: 'Background work handed to a worker or an agent, retried until it is done.',
        note: 'A message comes back to the queue until a worker confirms it finished.',
        inUse: (a) => counted(a.counts.queues, 'queue'),
    },
    {
        id: 'secrets',
        area: 'Data',
        label: 'Secrets',
        icon: LockKeyhole,
        what: 'Third-party keys and other values your sandboxes, agents and apps read.',
        note: 'Values are write-only: only their names show here.',
        inUse: (a) => counted(a.counts.secrets, 'secret'),
    },
    {
        id: 'domains',
        area: 'Domains and money',
        label: 'Domains',
        icon: Globe,
        what: 'Domains you bought or connected, and what each one serves.',
        inUse: (a) => counted(a.counts.domains, 'domain'),
    },
    {
        id: 'cards',
        area: 'Domains and money',
        label: 'Cards',
        icon: CreditCard,
        what: 'Virtual cards with spending limits, for agents that buy things.',
        inUse: (a) => counted(a.counts.cards, 'card'),
        designed: true,
    },
];

/** The kinds this console shows: designed ones only in the lab. */
export function visibleKinds(lab: boolean): readonly ResourceKind[] {
    return lab ? RESOURCE_KINDS : RESOURCE_KINDS.filter((k) => !k.designed);
}

/** A kind's page lead: what it is, then how it behaves. */
export function kindLead(kind: ResourceKind): string {
    return kind.note ? `${kind.what} ${kind.note}` : kind.what;
}
