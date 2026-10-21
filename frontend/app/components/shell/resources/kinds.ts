// The kinds of thing an account owns, as Resources and the sidebar name them.
// Kept apart from the model so the sidebar can list them without loading it.
// An automation's published interface is one of its apps, and an automation's
// tables are a database: there is one kind of each.
import { AppWindow, Database, FileText, FolderGit2, Globe, HardDrive, Mail, Phone, type LucideIcon } from 'lucide-react';

export type KindId = 'numbers' | 'domains' | 'email' | 'apps' | 'databases' | 'storage' | 'repos' | 'files';

export interface KindDef {
    id: KindId;
    label: string;
    icon: LucideIcon;
    /** What this kind is for, where it has nothing yet. */
    empty: string;
    /** What to ask NoClick for when there is none. */
    ask?: string;
    /** One and many, for "2 numbers". */
    noun: [string, string];
    /** How it's charged: `item` at a set price each (a number's month, a domain's year), `use` by what it uses; the rest are included. */
    billed?: 'item' | 'use';
    /** Only the hosted platform API serves it: listed where one is registered (`platform.tsx`). Databases are
     * listed everywhere, as an automation's tables are one, and a platform adds its own. */
    platform?: boolean;
    /** Other words people use for it, which the command palette matches. */
    keywords: string;
    /** Its page for getting one by hand (?kind=&new=1): `label` names it, `short` is the overview tile's button, and
     * a `bought` one is sold with a recurring charge, so it needs billing. */
    manual?: { label: string; short: string; bought: boolean };
}

export const KINDS: KindDef[] = [
    {
        id: 'numbers',
        label: 'Numbers',
        icon: Phone,
        empty: 'Phone numbers your agents answer calls and texts on.',
        ask: 'Get me a phone number my agents can answer calls and texts on.',
        noun: ['number', 'numbers'],
        billed: 'item',
        keywords: 'phone phones phone number phone numbers calls texts sms telephone',
        manual: { label: 'Buy a number', short: 'Buy', bought: true },
    },
    {
        id: 'domains',
        label: 'Domains',
        icon: Globe,
        empty: 'Domains for your websites and your agents’ email, registered in your name.',
        ask: 'Help me find a domain for my website and buy it.',
        noun: ['domain', 'domains'],
        billed: 'item',
        platform: true,
        keywords: 'domain dns domain names nameservers registrar url',
        manual: { label: 'Buy a domain', short: 'Buy', bought: true },
    },
    {
        id: 'email',
        label: 'Email',
        icon: Mail,
        empty: 'Email addresses on your domains: mail sent to one arrives here, and you answer it from the same address.',
        ask: 'Set up an email address on my domain.',
        noun: ['address', 'addresses'],
        billed: 'use',
        platform: true,
        keywords: 'mail inbox inboxes email address mailbox',
        manual: { label: 'New address', short: 'New', bought: false },
    },
    {
        id: 'apps',
        label: 'Websites',
        icon: AppWindow,
        empty: 'Websites at addresses of their own: the interfaces you publish from your automations, and sites deployed from your code.',
        ask: 'Build a small website for my team and publish it.',
        noun: ['website', 'websites'],
        billed: 'use',
        platform: true,
        keywords: 'site sites website web pages hosting deploys deployments published interfaces apps',
    },
    {
        id: 'databases',
        label: 'Databases',
        icon: Database,
        empty: 'Where your automations keep their tables, and the SQL databases your websites and agents keep their data in.',
        ask: 'Set up a table my automations can keep records in.',
        noun: ['database', 'databases'],
        billed: 'use',
        keywords: 'database db sql tables data postgres sqlite',
    },
    {
        id: 'storage',
        label: 'Storage',
        icon: HardDrive,
        empty: 'Buckets of files your websites and agents keep, like uploads and exports. They make one when they need it, private unless you make it public.',
        ask: 'Set up a bucket my website can keep its uploads in.',
        noun: ['bucket', 'buckets'],
        billed: 'use',
        platform: true,
        keywords: 'bucket buckets uploads s3 blobs object storage',
    },
    {
        id: 'repos',
        label: 'Code',
        icon: FolderGit2,
        empty: 'The code your websites deploy from and your agents work on, each in a repository of its own.',
        noun: ['repository', 'repositories'],
        billed: 'use',
        platform: true,
        keywords: 'repo repos repository repositories git github source',
    },
    {
        id: 'files',
        label: 'Files',
        icon: FileText,
        empty: 'Uploads, outputs and what agents save in their workspaces show up here as they work.',
        noun: ['file', 'files'],
        keywords: 'file uploads documents outputs workspaces pdf',
    },
];

export function kindDef(id: KindId): KindDef {
    return KINDS.find((k) => k.id === id)!;
}

/** The kinds this instance can have: the platform's kinds need a platform. */
export function visibleKinds({ platform }: { platform: boolean }): KindDef[] {
    return KINDS.filter((k) => !k.platform || platform);
}

/** The search params a body keeps where it is inside its item: a repo's, a database's, an address's. */
export const INNER_PARAMS = ['path', 'ref', 'view', 'sha', 'table', 'thread', 'compose'] as const;

/** Resources' address for a kind (null: the overview), one of its items or its page for getting one, as
 *  `navigateToTab` params: whatever belonged to the page before (an item, a buy page, a place inside an item) goes. */
export function resourceAddress(kind: KindId | null, at: { resource?: string; manual?: boolean } = {}): Record<string, string | null> {
    return {
        kind,
        resource: at.resource ?? null,
        new: at.manual ? '1' : null,
        name: null,
        ...Object.fromEntries(INNER_PARAMS.map((p) => [p, null])),
    };
}
