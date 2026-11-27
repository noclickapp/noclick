// What each "New …" dialog says, for everything the console shows code to make rather than a form: its mark, title
// and line, the docs page it links to, and what its prompt asks a coding agent to set up. The code itself is the
// kind's in `snippets.ts` (`NEW_SNIPPETS`), where the snippet test holds every place's code to both SDKs.
import { Bot, UserRound, Webhook, Zap, type LucideIcon } from 'lucide-react';
import { RESOURCE_KINDS, type ResourceKindId } from '@/screens/console/resourceKinds';
import type { CoderTask, NewKind } from './snippets';

export interface NewInCodeKind extends CoderTask {
    mark: LucideIcon;
    title: string;
    /** What it is and what running the code again does, in a line or two. */
    description: string;
    /** The console page whose button opens it (`?new=<kind>` there), which the palette goes to; none for an agent's own. */
    page?: string;
}

/** A resource's mark, as Resources draws its kind, and its page there. */
const resource = (id: ResourceKindId) => ({ mark: RESOURCE_KINDS.find((k) => k.id === id)!.icon, page: `resources/${id}` });

export const NEW_IN_CODE: Readonly<Record<NewKind, NewInCodeKind>> = {
    agent: {
        mark: Bot,
        title: 'New agent',
        page: '',
        description: 'Agents are made in your code. Run this once and the agent shows up here; running it again finds the same one.',
        guide: 'guide/agents',
        goal: 'build an agent',
        ask: 'Ask me what the agent should do and where it runs, then build it.',
    },
    trigger: {
        mark: Zap,
        title: 'Add a trigger',
        description: 'What wakes the agent besides a message. Adding the same trigger again keeps the one it has; mail and calls are set on an inbox or a phone number.',
        guide: 'guide/triggers',
        goal: 'wake my agent on more than a message',
        ask: 'Ask me what should wake it (a schedule, a webhook, an event in one of my connected apps, one of NoClick’s own events, or each message on a queue), then add that trigger to it in code.',
    },
    user: {
        mark: UserRound,
        title: 'New user',
        page: 'users',
        description: 'A user is someone your product acts for, made by your own id for them the first time your code acts for them.',
        guide: 'guide/users',
        goal: 'give each of my product’s users a NoClick user',
        ask: 'Find where my product signs people up, and make a NoClick user for each, keyed by my own id for them.',
    },
    webhook: {
        mark: Webhook,
        title: 'New endpoint',
        page: 'settings/webhooks',
        description: 'NoClick POSTs each event you name to this URL, signed. The run that creates it prints its signing secret; later runs find it.',
        guide: 'guide/webhooks',
        goal: 'receive NoClick’s events on my server',
        ask: 'Ask me which events my server should hear, add a route that verifies each delivery with its signing secret, register it, and keep the secret in .env beside the key.',
    },
    app: {
        ...resource('apps'),
        title: 'New app',
        description: 'An app deploys a repo to its own URL. The code makes both the first time, then each run deploys what the folder holds.',
        guide: 'guide/apps',
        goal: 'deploy an app on NoClick',
        ask: 'Ask me what the app should do, build it, commit it to a NoClick repo and deploy it as an app, then tell me its URL.',
    },
    repo: {
        ...resource('repos'),
        title: 'New repo',
        description: 'A plain git repo your code and agents commit to and any git client pushes to. Running it again finds the same one.',
        guide: 'guide/repos',
        goal: 'keep code in a NoClick repo',
        ask: 'Ask me what the repo holds, make it, and push this project to it, or commit to it from my code.',
    },
    inbox: {
        ...resource('inboxes'),
        title: 'New inbox',
        description: 'An email address whose mail wakes an agent. Running it again finds the same inbox and gives it your agent.',
        guide: 'guide/inboxes',
        goal: 'give an agent its own email address',
        ask: 'Ask me which agent answers its mail (build one if I have none), then make an inbox whose mail wakes it, and tell me its address.',
    },
    channel: {
        ...resource('channels'),
        title: 'New channel',
        description: 'Where your agents, your users and agents from elsewhere talk. Running it again finds the same channel and sets its members to yours.',
        guide: 'guide/channels',
        goal: 'put my agents and users in a channel',
        ask: 'Ask me what the channel is for and who talks in it, then make it with them as members.',
    },
    sandbox: {
        ...resource('sandboxes'),
        title: 'New sandbox',
        description: 'A Linux machine your code runs commands in, billed by the second until it ends. This one ends with the code.',
        guide: 'guide/sandboxes',
        goal: 'run code in a NoClick sandbox',
        ask: 'Ask me what it should run, then start a sandbox, run it there and end the sandbox when it’s done.',
    },
    'browser-profile': {
        ...resource('browser-profiles'),
        title: 'New browser profile',
        description: 'One person’s sign-ins, used only by its user’s browsers and agents. The code makes the profile and the link where its person signs in.',
        guide: 'guide/browser',
        goal: 'keep a person’s sign-ins in a browser profile',
        ask: 'Ask me whose sign-ins it keeps and for which site, make the profile, and have that person sign in at its link.',
    },
    database: {
        ...resource('databases'),
        title: 'New database',
        description: 'A SQL database for an app or an agent: SQLite unless you ask for Postgres. Running it again finds the same one.',
        guide: 'guide/databases',
        goal: 'give my code a NoClick database',
        ask: 'Ask me what it stores, make the database and its tables in code, and read and write it from my code.',
    },
    bucket: {
        ...resource('storage'),
        title: 'New bucket',
        description: 'Files by key, private unless you make it public, with signed links. Running it again finds the same bucket.',
        guide: 'guide/storage',
        goal: 'store files in a NoClick bucket',
        ask: 'Ask me what files it holds and who reads them, make the bucket, and put and read its files from my code.',
    },
    volume: {
        ...resource('volumes'),
        title: 'New volume',
        description: 'A folder that sandboxes and agents mount, kept between their runs. Running it again finds the same one.',
        guide: 'guide/volumes',
        goal: 'keep a folder my sandboxes and agents mount',
        ask: 'Ask me what goes in it, make the volume, and mount it where my code runs.',
    },
    dict: {
        ...resource('dicts'),
        title: 'New key-value store',
        description: 'Small shared state: what’s been handled, counters, locks, a cache that empties itself. Running it again finds the same store.',
        guide: 'guide/dicts',
        goal: 'keep small shared state in a key-value store',
        ask: 'Ask me what it keeps track of, make the store, and use it from my code.',
    },
    queue: {
        ...resource('queues'),
        title: 'New queue',
        description: 'Work handed from your app to a worker or an agent, retried until it’s acknowledged. Running it again finds the same queue.',
        guide: 'guide/queues',
        goal: 'hand work from my app to a worker through a queue',
        ask: 'Ask me what work goes on it, make the queue, and write the code that puts messages on it and the worker that takes each off and acknowledges it.',
    },
};

/** What the dialog's link says: "The inboxes guide". */
export const guideLabel = (guide: string) => `The ${guide.split('/').pop()!.replace(/-/g, ' ')} guide`;
