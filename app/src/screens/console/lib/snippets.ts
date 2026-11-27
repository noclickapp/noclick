// Every snippet the console shows, built in one place. Each is self-contained
// (import, the idempotent lookup, the call), reads $NOCLICK_API_KEY, and is
// checked by snippets.test.ts: type-checked against the TypeScript client, and
// its names and keyword arguments against the Python one.
import { CONSOLE_BASE_URL, DEFAULT_BASE_URL } from 'noclick';
import { API_KEY_ENV } from '@/sdk/source';
import type { ConsoleLanguage } from './highlightCode';
import { MCP_URL } from './mcpUrl';

export interface Snippet {
    python: string;
    typescript: string;
}

export interface CodeTab {
    id: string;
    label: string;
    code: string;
    /** How to colour it, where the id doesn't say (`python` and `env` do). */
    language?: ConsoleLanguage;
}

const PY = 'import noclick';
const lit = (value: string) => JSON.stringify(value);
const lines = (...parts: string[]) => parts.join('\n');

export { MCP_URL };

export function snippetTabs(snippet: Snippet): CodeTab[] {
    return [
        { id: 'python', label: 'Python', code: snippet.python },
        { id: 'typescript', label: 'TypeScript', code: snippet.typescript },
    ];
}

/** Where a New dialog's code makes its thing: for one of your users, on an agent (by name), in a workspace (by id). */
export interface NewPlace {
    user?: string | null;
    agent?: string;
    workspace?: string;
    /** On an account agent's memory, the user whose own notes it goes in (none: the account's). */
    layer?: string | null;
}

/** The most a line of a New dialog's code takes before it's broken, so the dialog never scrolls sideways. */
const WIDTH = 88;

/** `head(args)`, on one line while it fits, else an argument a line. */
function pyCall(head: string, args: readonly string[], after = ''): string {
    const one = `${head}(${args.join(', ')})${after}`;
    return one.length <= WIDTH ? one : lines(`${head}(`, ...args.map((arg) => `    ${arg},`), `)${after}`);
}

/** `head(first, { options })`, on one line while it fits, else an option a line. */
function tsCall(head: string, first: string, options: readonly string[], after = ''): string {
    const one = `${head}(${first}, { ${options.join(', ')} })${after}`;
    return one.length <= WIDTH ? one : lines(`${head}(${first}, {`, ...options.map((option) => `    ${option},`), `})${after}`);
}

/** The `user` argument, when the thing is one of your users'. */
const pyUser = ({ user }: NewPlace) => (user ? [`user=${lit(user)}`] : []);
const tsUser = ({ user }: NewPlace) => (user ? [`user: ${lit(user)}`] : []);

/** The agent the snippets make the first time they run: `support`, doing what `instructions` says. */
function agentLines(place: NewPlace = {}, instructions = 'You answer billing questions.'): Snippet {
    return {
        python: pyCall('agent = noclick.Agent.from_name', ['"support"', 'create_if_missing=True', `instructions=${lit(instructions)}`, ...pyUser(place)]),
        typescript: tsCall('const agent = Agent.fromName', '"support"', ['createIfMissing: true', `instructions: ${lit(instructions)}`, ...tsUser(place)], ';'),
    };
}

const AGENT = agentLines();

/**
 * What each kind's New dialog and its empty list show: the code that makes one. Run again, each finds the same one
 * (but a sandbox, which lasts its run), and each uses it, since a reference by name sends nothing until it's used.
 */
export const NEW_SNIPPETS = {
    agent: (): Snippet => ({
        python: lines(PY, '', AGENT.python, 'print(agent.id)'),
        typescript: lines('import { Agent } from "noclick";', '', AGENT.typescript, 'console.log((await agent.hydrate()).id);'),
    }),
    trigger: (place: NewPlace): Snippet => {
        const name = lit(place.agent ?? 'support');
        return {
            python: lines(
                PY,
                '',
                pyCall('agent = noclick.Agent.from_name', [name, ...pyUser(place)]),
                '# A schedule; noclick.OnWebhook, OnEvent, OnPlatformEvent and OnQueue wake it too.',
                pyCall('schedule = noclick.Cron', ['"0 8 * * 1-5"', 'tz="Europe/London"', 'message="Post the overnight summary."']),
                'print(agent.add_trigger(schedule).next_run)'
            ),
            typescript: lines(
                'import { Agent, Cron } from "noclick";',
                '',
                place.user ? tsCall('const agent = Agent.fromName', name, tsUser(place), ';') : `const agent = Agent.fromName(${name});`,
                '// A schedule; OnWebhook, OnEvent, OnPlatformEvent and OnQueue wake it too.',
                tsCall('const schedule = new Cron', '"0 8 * * 1-5"', ['tz: "Europe/London"', 'message: "Post the overnight summary."'], ';'),
                'console.log((await agent.addTrigger(schedule)).nextRun);'
            ),
        };
    },
    /** A user is keyed by your own id for them: here `user_42`. */
    user: (): Snippet => ({
        python: lines(PY, '', pyCall('user = noclick.User.from_id', ['"user_42"', 'create_if_missing=True', 'email="ana@example.com"']), 'print(user.status)'),
        typescript: lines(
            'import { User } from "noclick";',
            '',
            tsCall('const user = User.fromId', '"user_42"', ['createIfMissing: true', 'email: "ana@example.com"'], ';'),
            'console.log((await user.hydrate()).status);'
        ),
    }),
    webhook: (place: NewPlace): Snippet => {
        const url = '"https://api.yourco.test/noclick/events"';
        const events = '["operation.succeeded", "operation.failed", "human.answered"]';
        return {
            python: lines(
                PY,
                '',
                pyCall('hook = noclick.Webhook.from_name', [url, 'create_if_missing=True', `events=${events}`, ...pyUser(place)]),
                'print(hook.secret)  # its signing secret, the first run only'
            ),
            typescript: lines(
                'import { Webhook } from "noclick";',
                '',
                tsCall('const hook = Webhook.fromName', url, ['createIfMissing: true', `events: ${events}`, ...tsUser(place)], ';'),
                'console.log((await hook.hydrate()).secret); // its signing secret, the first run only'
            ),
        };
    },
    app: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('repo = noclick.Repo.from_name', ['"booking"', 'create_if_missing=True', ...pyUser(place)]),
            'repo.commit("./site", message="Deploy the site")  # commits only what changed',
            pyCall('app = noclick.Project.from_name', ['"booking"', 'repo=repo', 'create_if_missing=True', ...pyUser(place)]),
            'print(app.deploy().wait().url)'
        ),
        typescript: lines(
            'import { Project, Repo } from "noclick";',
            '',
            tsCall('const repo = Repo.fromName', '"booking"', ['createIfMissing: true', ...tsUser(place)], ';'),
            'await repo.commit("./site", { message: "Deploy the site" }); // commits only what changed',
            tsCall('const app = Project.fromName', '"booking"', ['repo', 'createIfMissing: true', ...tsUser(place)], ';'),
            'console.log((await (await app.deploy()).wait()).url);'
        ),
    }),
    repo: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('repo = noclick.Repo.from_name', ['"agent-tools"', 'create_if_missing=True', ...pyUser(place)]),
            'print(repo.clone_url(write=True))  # git push here; it works for an hour'
        ),
        typescript: lines(
            'import { Repo } from "noclick";',
            '',
            tsCall('const repo = Repo.fromName', '"agent-tools"', ['createIfMissing: true', ...tsUser(place)], ';'),
            'console.log(await repo.cloneUrl({ write: true })); // git push here; it works for an hour'
        ),
    }),
    inbox: (place: NewPlace): Snippet => {
        const agent = agentLines(place, 'You answer customer email.');
        return {
            python: lines(PY, '', agent.python, pyCall('inbox = noclick.Inbox.from_name', ['"support"', 'create_if_missing=True', 'agent=agent', ...pyUser(place)]), 'print(inbox.address)'),
            typescript: lines(
                'import { Agent, Inbox } from "noclick";',
                '',
                agent.typescript,
                tsCall('const inbox = Inbox.fromName', '"support"', ['createIfMissing: true', 'agent', ...tsUser(place)], ';'),
                'console.log((await inbox.hydrate()).address);'
            ),
        };
    },
    /** In a workspace it holds no agent: an agent there must be one of the workspace's members. */
    channel: (place: NewPlace): Snippet => {
        const ws = place.workspace;
        return {
            python: lines(
                PY,
                '',
                ...(ws ? [] : [AGENT.python]),
                pyCall('channel = noclick.Channel.from_name', ['"launch"', 'create_if_missing=True', ws ? `workspace=${lit(ws)}` : 'members=[agent]', ...pyUser(place)]),
                'print(channel.id)'
            ),
            typescript: lines(
                `import { ${ws ? '' : 'Agent, '}Channel } from "noclick";`,
                '',
                ...(ws ? [] : [AGENT.typescript]),
                tsCall('const channel = Channel.fromName', '"launch"', ['createIfMissing: true', ws ? `workspace: ${lit(ws)}` : 'members: [agent]', ...tsUser(place)], ';'),
                'console.log((await channel.hydrate()).id);'
            ),
        };
    },
    sandbox: (place: NewPlace): Snippet => ({
        python: lines(PY, '', `${pyCall('with noclick.Sandbox.create', ['"python"', 'timeout_s=600', ...pyUser(place)])} as sb:`, `    print(sb.exec("python -c 'print(6 * 7)'").stdout)`),
        typescript: lines(
            'import { Sandbox } from "noclick";',
            '',
            `const sb = await Sandbox.create({ ${['image: "python"', 'timeoutS: 600', ...tsUser(place)].join(', ')} });`,
            `console.log((await sb.exec("python -c 'print(6 * 7)'")).stdout);`,
            'await sb.terminate();'
        ),
    }),
    'browser-profile': (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('profile = noclick.BrowserProfile.from_name', ['"ana-work"', 'create_if_missing=True', ...pyUser(place)]),
            'login = profile.login("https://portal.example.com", reason="to download your invoices")',
            'print(login.url)  # where its person signs in, in a live browser'
        ),
        typescript: lines(
            'import { BrowserProfile } from "noclick";',
            '',
            tsCall('const profile = BrowserProfile.fromName', '"ana-work"', ['createIfMissing: true', ...tsUser(place)], ';'),
            tsCall('const login = await profile.login', '"https://portal.example.com"', ['reason: "to download your invoices"'], ';'),
            'console.log(login.url); // where its person signs in, in a live browser'
        ),
    }),
    database: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('db = noclick.Database.from_name', ['"orders"', 'create_if_missing=True', ...pyUser(place)]),
            'db.execute("create table if not exists orders (id text primary key, item text)")',
            'print(db.query("select count(*) as n from orders").rows[0]["n"])'
        ),
        typescript: lines(
            'import { Database } from "noclick";',
            '',
            tsCall('const db = Database.fromName', '"orders"', ['createIfMissing: true', ...tsUser(place)], ';'),
            'await db.execute("create table if not exists orders (id text primary key, item text)");',
            'console.log((await db.query("select count(*) as n from orders")).rows[0].n);'
        ),
    }),
    bucket: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('bucket = noclick.Bucket.from_name', ['"uploads"', 'create_if_missing=True', ...pyUser(place)]),
            'bucket.put("hello.txt", "Hello from NoClick")',
            'print(bucket.signed_url("hello.txt", expires_in=3600))'
        ),
        typescript: lines(
            'import { Bucket } from "noclick";',
            '',
            tsCall('const bucket = Bucket.fromName', '"uploads"', ['createIfMissing: true', ...tsUser(place)], ';'),
            'await bucket.put("hello.txt", "Hello from NoClick");',
            'console.log(await bucket.signedUrl("hello.txt", { expiresIn: 3600 }));'
        ),
    }),
    volume: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('vol = noclick.Volume.from_name', ['"datasets"', 'create_if_missing=True', ...pyUser(place)]),
            'vol.write("/raw/hello.txt", "Hello from NoClick")',
            `${pyCall('with noclick.Sandbox.create', ['volumes={"/data": vol}', ...pyUser(place)])} as sb:`,
            '    print(sb.exec("cat /data/raw/hello.txt").stdout)'
        ),
        typescript: lines(
            'import { Sandbox, Volume } from "noclick";',
            '',
            tsCall('const vol = Volume.fromName', '"datasets"', ['createIfMissing: true', ...tsUser(place)], ';'),
            'await vol.write("/raw/hello.txt", "Hello from NoClick");',
            `const sb = await Sandbox.create({ ${['volumes: { "/data": vol }', ...tsUser(place)].join(', ')} });`,
            'console.log((await sb.exec("cat /data/raw/hello.txt")).stdout);',
            'await sb.terminate();'
        ),
    }),
    dict: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('seen = noclick.Dict.from_name', ['"processed-orders"', 'create_if_missing=True', ...pyUser(place)]),
            'if seen.put_if_absent("o_1841", {"status": "refunded"}):',
            '    print("First time we handle o_1841")',
            'print(seen.increment("refunds-today"))'
        ),
        typescript: lines(
            'import { Dict } from "noclick";',
            '',
            tsCall('const seen = Dict.fromName', '"processed-orders"', ['createIfMissing: true', ...tsUser(place)], ';'),
            'if (await seen.putIfAbsent("o_1841", { status: "refunded" })) {',
            '    console.log("First time we handle o_1841");',
            '}',
            'console.log(await seen.increment("refunds-today"));'
        ),
    }),
    /** Pending until someone signs in to the account at its link, which the code prints to send them. */
    connection: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('gmail = noclick.Connection.from_name', ['"gmail"', 'integration="gmail"', 'create_if_missing=True', ...pyUser(place)]),
            'if not gmail.connected:',
            '    link = gmail.connect_link(reason="to send your weekly summaries")',
            '    print(link.url)  # send it to whoever signs in to the account'
        ),
        typescript: lines(
            'import { Connection } from "noclick";',
            '',
            tsCall('const gmail = Connection.fromName', '"gmail"', ['integration: "gmail"', 'createIfMissing: true', ...tsUser(place)], ';'),
            'if (!(await gmail.hydrate()).connected) {',
            '    const link = await gmail.connectLink({ reason: "to send your weekly summaries" });',
            '    console.log(link.url); // send it to whoever signs in to the account',
            '}'
        ),
    }),
    /** Its values come from the program's own environment, never from the code. */
    secret: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            'import os',
            '',
            "# The value comes from this program's environment (its .env), never from the code.",
            pyCall('stripe = noclick.Secret.from_name', ['"stripe"', 'values={"STRIPE_API_KEY": os.environ["STRIPE_API_KEY"]}', 'create_if_missing=True', ...pyUser(place)]),
            'print(stripe.keys)  # its names; a value never comes back'
        ),
        typescript: lines(
            'import { Secret } from "noclick";',
            '',
            "// The value comes from this program's environment (its .env), never from the code.",
            tsCall('const stripe = Secret.fromName', '"stripe"', ['values: { STRIPE_API_KEY: process.env.STRIPE_API_KEY! }', 'createIfMissing: true', ...tsUser(place)], ';'),
            'console.log((await stripe.hydrate()).keys); // its names; a value never comes back'
        ),
    }),
    /** A note the agent keeps: every turn starts with its name and description. Saving it again replaces it. */
    memory: (place: NewPlace): Snippet => {
        const name = lit(place.agent ?? 'support');
        const rules = 'rules = "Refund within 30 days. Over $500, ask a person first."';
        const layer = place.layer ?? place.user;
        return {
            python: lines(
                PY,
                '',
                pyCall('agent = noclick.Agent.from_name', [name, ...pyUser(place)]),
                rules,
                pyCall('entry = agent.memory.save', ['"refunds"', 'rules', 'description="Our refund rules"', ...pyUser({ user: layer })]),
                'print(entry.version)'
            ),
            typescript: lines(
                'import { Agent } from "noclick";',
                '',
                place.user ? tsCall('const agent = Agent.fromName', name, tsUser(place), ';') : `const agent = Agent.fromName(${name});`,
                `const ${rules};`,
                tsCall('const entry = await agent.memory.save', '"refunds", rules', ['description: "Our refund rules"', ...tsUser({ user: layer })], ';'),
                'console.log(entry.version);'
            ),
        };
    },
    /** Asked once, by a key that names `machines:vetting`; acceptance of the usage policy is a person's, said to the code. */
    machines: (): Snippet => {
        const fields = [
            ['company_name', 'companyName', '"Acme Inc."'],
            ['website', 'website', '"https://acme.com"'],
            ['country', 'country', '"US"'],
            ['use_case', 'useCase', '"Support agents that answer customer email."'],
            ['accept_usage_policy', 'acceptUsagePolicy', null],
        ] as const;
        return {
            python: lines(
                PY,
                'import datetime as dt',
                '',
                'access = noclick.Machine.access()',
                'if access.status in ("not_submitted", "rejected"):',
                '    access = noclick.Machine.request_access(',
                ...fields.map(([py, , value]) => `        ${py}=${value ?? 'True'},`),
                '        # Who read the usage policy and said they accept it, and when they said so.',
                '        accepted_by={"name": "Ana Lima", "email": "ana@acme.com"},',
                '        accepted_at=dt.datetime.now(dt.timezone.utc),',
                '    )',
                'print(access.status, access.reason)'
            ),
            typescript: lines(
                'import { Machine } from "noclick";',
                '',
                'let access = await Machine.access();',
                'if (access.status === "not_submitted" || access.status === "rejected") {',
                '    access = await Machine.requestAccess({',
                ...fields.map(([, ts, value]) => `        ${ts}: ${value ?? 'true'},`),
                '        // Who read the usage policy and said they accept it, and when they said so.',
                '        acceptedBy: { name: "Ana Lima", email: "ana@acme.com" },',
                '        acceptedAt: new Date(),',
                '    });',
                '}',
                'console.log(access.status, access.reason);'
            ),
        };
    },
    card: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('card = noclick.Card.from_name', [
                '"office-supplies"',
                'create_if_missing=True',
                'limit_usd=500',
                'merchants=["office_supplies"]',
                'require_approval_above_usd=100',
                ...pyUser(place),
            ]),
            'print(card.last4)  # its last four digits; a person reveals the rest on its page'
        ),
        typescript: lines(
            'import { Card } from "noclick";',
            '',
            tsCall('const card = Card.fromName', '"office-supplies"', [
                'createIfMissing: true',
                'limitUsd: 500',
                'merchants: ["office_supplies"]',
                'requireApprovalAboveUsd: 100',
                ...tsUser(place),
            ], ';'),
            'console.log((await card.hydrate()).last4); // its last four digits only'
        ),
    }),
    queue: (place: NewPlace): Snippet => ({
        python: lines(
            PY,
            '',
            pyCall('jobs = noclick.Queue.from_name', ['"invoices"', 'create_if_missing=True', ...pyUser(place)]),
            'jobs.put({"invoice": "INV-1042"})',
            'for msg in jobs.iterate(lease_s=60, stop_when_empty=True):',
            '    print("Sending", msg.body["invoice"])',
            '    msg.ack()'
        ),
        typescript: lines(
            'import { Queue } from "noclick";',
            '',
            tsCall('const jobs = Queue.fromName', '"invoices"', ['createIfMissing: true', ...tsUser(place)], ';'),
            'await jobs.put({ invoice: "INV-1042" });',
            'for await (const msg of jobs.iterate({ leaseS: 60, stopWhenEmpty: true })) {',
            '    console.log("Sending", msg.body);',
            '    await msg.ack();',
            '}'
        ),
    }),
} satisfies Record<string, (place: NewPlace) => Snippet>;

export type NewKind = keyof typeof NEW_SNIPPETS;

/** The first call: the Quickstart's example and the empty lists'. */
export const OPERATIONS_EMPTY: Snippet = {
    python: lines(PY, '', AGENT.python, 'print(agent.message("hi").text)'),
    typescript: lines('import { Agent } from "noclick";', '', AGENT.typescript, 'console.log((await agent.message("hi")).text);'),
};

export const TOOL_CALLS_EMPTY: Snippet = {
    python: lines(
        PY,
        'user = noclick.User.from_id("user_42", create_if_missing=True)',
        'with noclick.as_user(user):',
        '    print(noclick.Toolkit(["search"]).call("search", {"query": "noclick"}))'
    ),
    typescript: lines(
        'import { Toolkit, User } from "noclick";',
        'const user = User.fromId("user_42", { createIfMissing: true });',
        'console.log(await new Toolkit(["search"]).call("search", { query: "noclick" }, { user }));'
    ),
};

export const HUMAN_REQUESTS_EMPTY: Snippet = {
    python: lines(
        PY,
        'user = noclick.User.from_id("user_42", create_if_missing=True, email="ana@example.com")',
        'print(user.human.approve("Send the weekly summary to your team?").wait())'
    ),
    typescript: lines(
        'import { User } from "noclick";',
        'const user = User.fromId("user_42", { createIfMissing: true, email: "ana@example.com" });',
        'console.log(await (await user.human.approve("Send the weekly summary to your team?")).wait());'
    ),
};

export const MACHINES_START: Snippet = {
    python: lines(PY, 'box = noclick.Machine.create("support-box", size="small", max_monthly_usd=32)', 'print(box.status)'),
    typescript: lines(
        'import { Machine } from "noclick";',
        'const box = await Machine.create("support-box", { size: "small", maxMonthlyUsd: 32 });',
        'console.log(box.status);'
    ),
};

export const PHONE_NUMBERS_EMPTY: Snippet = {
    python: lines(PY, 'number = noclick.PhoneNumber.buy(noclick.PhoneNumber.available(area_code=415)[0], max_monthly_usd=5)', 'print(number.id)'),
    typescript: lines(
        'import { PhoneNumber } from "noclick";',
        'const [available] = await PhoneNumber.available({ areaCode: 415 });',
        'const number = await PhoneNumber.buy(available, { maxMonthlyUsd: 5 });',
        'console.log(number.id);'
    ),
};

export const POLICY_EMPTY: Snippet = {
    python: lines(PY, 'noclick.Policy.set(require_approval=["gmail.send_email_message"], deny=["*.delete_*"])'),
    typescript: lines(
        'import { Policy } from "noclick";',
        'await Policy.set({ requireApproval: ["gmail.send_email_message"], deny: ["*.delete_*"] });'
    ),
};

/** A rule with a condition and an approver, set from code: the console keeps it, never edits it. */
export const POLICY_RULE: Snippet = {
    python: lines(PY, 'noclick.Policy.add(noclick.Rule("stripe.create_refund", when="args.amount > 10000", approver="finance@acme.com"))'),
    typescript: lines(
        'import { Policy, Rule } from "noclick";',
        'await Policy.add([new Rule("stripe.create_refund", { when: "args.amount > 10000", approver: "finance@acme.com" })]);'
    ),
};

export const INSTALL_TABS: CodeTab[] = [
    { id: 'python', label: 'Python', code: 'pip install noclick', language: 'bash' },
    { id: 'typescript', label: 'TypeScript', code: 'npm install noclick', language: 'bash' },
];

/** The public docs site, beside the console on the same host. */
export const DOCS_URL = `${new URL(CONSOLE_BASE_URL).origin}/docs`;

/** What a prompt has the coding agent build: "help me {goal}", its step 3 (`ask`), and the docs page it reads. */
export interface CoderTask {
    goal: string;
    ask: string;
    /** A page of the docs, as `docsUrl` takes it: `guide/inboxes`. */
    guide: string;
    /** Scopes the prompt's key also holds, beyond what a key with every scope (`*`) does: only what the task needs. */
    scopes?: readonly string[];
}

/** Whose it is and where it goes, for the coding agent, from a dialog's place. */
function placeNote({ user, agent, workspace, layer }: NewPlace): string {
    return [
        agent ? ` It's for my agent ${lit(agent)}.` : '',
        workspace ? ` It goes in my workspace ${workspace}.` : '',
        user ? ` Make it as my user ${lit(user)} (my own id for them), with user=${lit(user)}.` : '',
        layer ? ` It goes in the notes my agent keeps for my user ${lit(layer)}, with user=${lit(layer)}.` : '',
    ].join('');
}

/**
 * The prompt a coding agent is handed. It carries a one-time setup code, never a key: the agent's one command
 * trades the code for a key that goes from the response straight into the project's .env, so the key never
 * passes through the agent's context. `apiBase` is the API the console talks to, which minted the code.
 */
export function coderPrompt(setupCode: string, task: CoderTask, { apiBase = DEFAULT_BASE_URL, place = {} }: { apiBase?: string; place?: NewPlace } = {}): string {
    return lines(
        `Set up NoClick in this project, then help me ${task.goal}.`,
        '',
        '1. Install the SDK for this project\'s language: `pip install noclick` (Python) or `npm install noclick` (TypeScript).',
        '2. Save my API key to .env with this command. It never prints the key, and its code works once, for 30 minutes:',
        `   curl -fsS -X POST ${apiBase}/v1/setup -d code=${setupCode} >> .env`,
        `   Make sure .env is in .gitignore. Never print, read or commit the key. The SDK reads ${API_KEY_ENV}, so load .env when the program starts. If the command fails, ask me for a fresh prompt.`,
        `3. ${task.ask}${placeNote(place)} The guide: ${DOCS_URL}/${task.guide}. Every class and method: ${DOCS_URL}/reference/python.`,
        '',
        `When it runs, what it made shows up in my console at ${CONSOLE_BASE_URL}.`
    );
}

/** The shell line that precedes a first call; the raw key only ever appears here. */
export function envExport(rawKey = '…'): string {
    return `export ${API_KEY_ENV}=${rawKey}`;
}

/** Operations drawer: Copy as Python / TS. */
export function operationWaitSnippet(operationId: string): Snippet {
    return {
        python: lines(PY, `print(noclick.Operation.from_id(${lit(operationId)}).wait())`),
        typescript: lines(
            'import { Operation } from "noclick";',
            `console.log(await Operation.fromId(${lit(operationId)}).wait());`
        ),
    };
}

/** Operations drawer: Copy as curl. */
export function operationCurl(operationId: string): string {
    return `curl -s ${DEFAULT_BASE_URL}/v1/operations/${encodeURIComponent(operationId)} \\\n  -H "Authorization: Bearer $${API_KEY_ENV}"`;
}

export interface AgentMessageInput {
    agentId: string;
    text: string;
    /** The User field's user (your id for them); null = your account. */
    user: string | null;
    conversation: string | null;
}

/** Try it: the call the composer just made, as code. */
export function agentMessageSnippet({ agentId, text, user, conversation }: AgentMessageInput): Snippet {
    const pyArgs = [lit(text), conversation ? `conversation=${lit(conversation)}` : null, user ? `user=${lit(user)}` : null]
        .filter(Boolean)
        .join(', ');
    const tsOptions = [conversation ? `conversation: ${lit(conversation)}` : null, user ? `user: ${lit(user)}` : null].filter(Boolean);
    const tsArgs = tsOptions.length ? `${lit(text)}, { ${tsOptions.join(', ')} }` : lit(text);
    return {
        python: lines(PY, `agent = noclick.Agent.from_id(${lit(agentId)})`, `print(agent.message(${pyArgs}).text)`),
        typescript: lines(
            'import { Agent } from "noclick";',
            `const agent = Agent.fromId(${lit(agentId)});`,
            `console.log((await agent.message(${tsArgs})).text);`
        ),
    };
}

/** An agent's page: message it by name, as its user when a user owns it. */
export function agentCodeSnippet(name: string, user: string | null): Snippet {
    return {
        python: lines(
            PY,
            '',
            `agent = noclick.Agent.from_name(${lit(name)}${user ? `, user=${lit(user)}` : ''})`,
            'reply = agent.message("Hello")',
            'print(reply.text)'
        ),
        typescript: lines(
            'import { Agent } from "noclick";',
            '',
            `const agent = Agent.fromName(${lit(name)}${user ? `, { user: ${lit(user)} }` : ''});`,
            'const reply = await agent.message("Hello");',
            'console.log(reply.text);'
        ),
    };
}

/** A user's page: act for them, here to give them a connection and send its link. */
export function userCodeSnippet(userId: string): Snippet {
    return {
        python: lines(
            PY,
            '',
            `with noclick.as_user(${lit(userId)}):`,
            '    gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True)',
            '    gmail.request(reason="to send your summaries")  # emails them its link'
        ),
        typescript: lines(
            'import { Connection } from "noclick";',
            '',
            `const gmail = Connection.fromName("gmail", { integration: "gmail", createIfMissing: true, user: ${lit(userId)} });`,
            'await gmail.request({ reason: "to send your summaries" }); // emails them its link'
        ),
    };
}

export const CLAUDE_CODE_MCP = `claude mcp add --transport http noclick ${MCP_URL} --header "Authorization: Bearer $${API_KEY_ENV}"`;

export const CURSOR_MCP = JSON.stringify(
    { mcpServers: { noclick: { url: MCP_URL, headers: { Authorization: `Bearer \${env:${API_KEY_ENV}}` } } } },
    null,
    2
);

/** The reveal-once step: the raw key is only in the env tab. */
export function keyRevealTabs(rawKey: string): CodeTab[] {
    return [
        { id: 'env', label: 'env', code: envExport(rawKey) },
        ...snippetTabs(OPERATIONS_EMPTY),
        { id: 'claude-code', label: 'Claude Code', code: CLAUDE_CODE_MCP },
        { id: 'cursor', label: 'Cursor', code: CURSOR_MCP },
    ];
}

/** The places a New dialog's code is shown for: the account's own, one of your users', a workspace's. */
const PLACES: Readonly<Record<string, NewPlace>> = {
    '': { agent: 'support' },
    '.user': { user: 'acme', agent: 'support' },
    '.workspace': { workspace: 'wsp_01', user: 'acme' },
    '.layer': { agent: 'support', layer: 'acme' },
};

/** Every snippet, for the compile check: the static ones, each kind's New in every place, and the made ones. */
export const ALL_SNIPPETS: Readonly<Record<string, Snippet>> = {
    ...Object.fromEntries(
        Object.entries(NEW_SNIPPETS).flatMap(([kind, make]) => Object.entries(PLACES).map(([suffix, place]) => [`new.${kind}${suffix}`, make(place)]))
    ),
    OPERATIONS_EMPTY,
    TOOL_CALLS_EMPTY,
    HUMAN_REQUESTS_EMPTY,
    MACHINES_START,
    PHONE_NUMBERS_EMPTY,
    POLICY_EMPTY,
    POLICY_RULE,
    operationWait: operationWaitSnippet('3f2a1b7c-0d4e-4f5a-9b6c-7d8e9f0a9c1e'),
    agentMessage: agentMessageSnippet({ agentId: 'a1b2c3d4-0000-4000-8000-000000000001', text: 'Hi "there"', user: 'acme', conversation: 'c-1' }),
    agentMessageAccount: agentMessageSnippet({ agentId: 'a1b2c3d4-0000-4000-8000-000000000001', text: 'hi', user: null, conversation: null }),
    agentCode: agentCodeSnippet('support', null),
    agentCodeUser: agentCodeSnippet('support', 'acme'),
    userCode: userCodeSnippet('acme'),
};
