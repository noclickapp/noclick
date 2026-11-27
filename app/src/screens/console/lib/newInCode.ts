// What each "New …" dialog says, for everything the console shows code to make rather than a form: its mark, title
// and line, the docs page it links to, and what its prompt asks a coding agent to set up. The code itself is the
// kind's in `snippets.ts` (`NEW_SNIPPETS`), where the snippet test holds every place's code to both SDKs.
import { Bot, NotebookPen, UserRound, Webhook, Zap, type LucideIcon } from 'lucide-react';
import { RESOURCE_KINDS, type ResourceKindId } from '@/screens/console/resourceKinds';
import { machinesPolicyUrl, NOCLICK_SITE } from './site';
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
        page: 'webhooks',
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
    connection: {
        ...resource('connections'),
        title: 'New connection',
        description: 'An account at a service, which your code and agents use by its name. It waits for someone to sign in at its link; running the code again finds the same one.',
        guide: 'guide/connections',
        goal: 'connect an account my code and agents act in',
        ask: 'Ask me which service and whose account it is, make the named connection in code, and give me its connect link to send to whoever signs in to that account. Never sign in to it yourself.',
    },
    secret: {
        ...resource('secrets'),
        title: 'New secret',
        description: 'Values your code reads from its environment, in sandboxes, agents’ shells and apps. The code reads each from its own environment, so a value is never typed here or into a prompt.',
        guide: 'guide/secrets',
        goal: 'keep a value such as an API key in a NoClick secret',
        ask: 'Ask me which values the secret holds, by name only. Read each value from this project’s environment or .env (if one is missing, ask me to add it there myself), never ask me to paste one to you, and never print, log or commit one. Then make the secret from them in code.',
    },
    memory: {
        mark: NotebookPen,
        title: 'New memory entry',
        description: 'A note the agent keeps across conversations: every turn starts with its name and description. Saving it again replaces it.',
        guide: 'guide/memory',
        goal: 'seed what my agent should know',
        ask: 'Ask me what my agent should know, then save each piece in code as a named memory entry with a one-line description of what it holds.',
    },
    machines: {
        // Its page shows the dialog only while the account may ask, so the palette doesn't offer it.
        ...resource('machines'),
        page: undefined,
        title: 'Ask for machines',
        description: 'NoClick reviews each account before its first machine. A person reads the machines usage policy and says they accept it; the code records who and when.',
        guide: 'guide/machines',
        goal: 'ask NoClick for machines for my company',
        ask: `Ask me for my company’s legal name, website, country and what its machines will run. Then ask me to read the machines usage policy (${machinesPolicyUrl(NOCLICK_SITE)}) and to say that I accept it for my company; don’t submit anything until I do. Submit the request in code, with my name and email as who accepted it and the moment I said so as when. The key this prompt gives you holds the machines:vetting scope it needs.`,
        scopes: ['machines:vetting'],
    },
    card: {
        // Cards are drawn in the lab alone, so the palette doesn't offer the page.
        ...resource('cards'),
        page: undefined,
        title: 'New card',
        description: 'A virtual card that spends your card balance within the limit you set. Running the code again finds the same card and sets its limits to yours.',
        guide: 'guide/cards',
        goal: 'issue a virtual card my agents pay with',
        ask: 'Ask me what the card is for, its spending limit and where it may be used, then issue it in code. Never print or keep its number.',
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
