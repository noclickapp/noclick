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
}

export const KINDS: KindDef[] = [
    { id: 'numbers', label: 'Numbers', icon: Phone, empty: 'Phone numbers your agents answer calls and texts on.', ask: 'Get me a phone number my agents can answer calls and texts on.', noun: ['number', 'numbers'], billed: 'item' },
    { id: 'domains', label: 'Domains', icon: Globe, empty: 'Domains for your websites and your agents’ email, registered in your name.', ask: 'Help me find a domain for my website and buy it.', noun: ['domain', 'domains'], billed: 'item', platform: true },
    {
        id: 'email',
        label: 'Email',
        icon: Mail,
        empty: 'Email addresses on your domains: mail sent to one arrives here, and you answer it from the same address.',
        ask: 'Set up an email address on my domain.',
        noun: ['address', 'addresses'],
        billed: 'use',
        platform: true,
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
    },
    {
        id: 'databases',
        label: 'Databases',
        icon: Database,
        empty: 'Where your automations keep their tables, and the SQL databases your websites and agents keep their data in.',
        ask: 'Set up a table my automations can keep records in.',
        noun: ['database', 'databases'],
        billed: 'use',
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
    },
    { id: 'repos', label: 'Code', icon: FolderGit2, empty: 'The code your websites deploy from and your agents work on, each in a repository of its own.', noun: ['repository', 'repositories'], billed: 'use', platform: true },
    { id: 'files', label: 'Files', icon: FileText, empty: 'Uploads, outputs and what agents save in their workspaces show up here as they work.', noun: ['file', 'files'] },
];

export function kindDef(id: KindId): KindDef {
    return KINDS.find((k) => k.id === id)!;
}

/** The kinds this instance can have: the platform's kinds need a platform. */
export function visibleKinds({ platform }: { platform: boolean }): KindDef[] {
    return KINDS.filter((k) => !k.platform || platform);
}
