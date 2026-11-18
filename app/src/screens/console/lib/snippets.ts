// Every snippet the console shows, built in one place. Each is self-contained
// (import, the idempotent lookup, the call), reads $NOCLICK_API_KEY, and is
// type-checked (TypeScript) and parsed (Python) by snippets.test.ts.
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

const AGENT_PY = lines(
    'agent = noclick.Agent.from_name(',
    '    "support",',
    '    create_if_missing=True,',
    '    instructions="You answer billing questions.",',
    ')'
);
const AGENT_TS = lines(
    'const agent = Agent.fromName("support", {',
    '    createIfMissing: true,',
    '    instructions: "You answer billing questions.",',
    '});'
);

/** "New agent": the code that makes one. An agent is made in code, never by a form in the console. */
export const NEW_AGENT: Snippet = {
    python: lines(PY, '', AGENT_PY),
    typescript: lines('import { Agent } from "noclick";', '', AGENT_TS),
};

/** The first call: the Quickstart's example and the empty lists'. */
export const OPERATIONS_EMPTY: Snippet = {
    python: lines(PY, '', AGENT_PY, 'print(agent.message("hi").text)'),
    typescript: lines(
        'import { Agent } from "noclick";',
        '',
        AGENT_TS,
        'console.log((await agent.message("hi")).text);'
    ),
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

/** A user is keyed by your own id for them: here `user_42`, created the first time it's used. */
export const USERS_EMPTY: Snippet = {
    python: lines(
        PY,
        'user = noclick.User.from_id("user_42", create_if_missing=True, email="ana@example.com")',
        'print(user.status)'
    ),
    typescript: lines(
        'import { User } from "noclick";',
        'const user = await User.fromId("user_42", { createIfMissing: true, email: "ana@example.com" }).hydrate();',
        'console.log(user.status);'
    ),
};

export const CHANNELS_EMPTY: Snippet = {
    python: lines(PY, AGENT_PY, 'noclick.Channel.create("launch", members=[agent])'),
    typescript: lines(
        'import { Agent, Channel } from "noclick";',
        AGENT_TS,
        'await Channel.create("launch", { members: [agent] });'
    ),
};

export const INBOXES_EMPTY: Snippet = {
    python: lines(PY, AGENT_PY, 'print(noclick.Inbox.create(agent=agent).address)'),
    typescript: lines(
        'import { Agent, Inbox } from "noclick";',
        AGENT_TS,
        'console.log((await Inbox.create({ agent })).address);'
    ),
};

export const SANDBOXES_EMPTY: Snippet = {
    python: lines(PY, 'sandbox = noclick.Sandbox.create("python", timeout_s=600)', 'print(sandbox.id)'),
    typescript: lines(
        'import { Sandbox } from "noclick";',
        'const sandbox = await Sandbox.create({ image: "python", timeoutS: 600 });',
        'console.log(sandbox.id);'
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

/**
 * The prompt a coding agent is handed. It carries a one-time setup code, never a key: the agent's one command
 * trades the code for a key that goes from the response straight into the project's .env, so the key never
 * passes through the agent's context. `apiBase` is the API the console talks to, which minted the code.
 */
export function coderPrompt(setupCode: string, apiBase: string = DEFAULT_BASE_URL): string {
    return lines(
        'Set up NoClick in this project, then build an agent with me.',
        '',
        '1. Install the SDK for this project\'s language: `pip install noclick` (Python) or `npm install noclick` (TypeScript).',
        '2. Save my API key to .env with this command. It never prints the key, and its code works once, for 30 minutes:',
        `   curl -fsS -X POST ${apiBase}/v1/setup -d code=${setupCode} >> .env`,
        `   Make sure .env is in .gitignore. Never print, read or commit the key. The SDK reads ${API_KEY_ENV}, so load .env when the program starts. If the command fails, ask me for a fresh prompt.`,
        `3. Ask me what the agent should do and where it runs, then build it. The guide: ${DOCS_URL}/guide. Every class and method: ${DOCS_URL}/reference/python.`,
        '',
        `When it runs, the agent shows up in my console at ${CONSOLE_BASE_URL}.`
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

/** Every static snippet, for the compile check. */
export const ALL_SNIPPETS: Readonly<Record<string, Snippet>> = {
    OPERATIONS_EMPTY,
    TOOL_CALLS_EMPTY,
    HUMAN_REQUESTS_EMPTY,
    USERS_EMPTY,
    CHANNELS_EMPTY,
    INBOXES_EMPTY,
    SANDBOXES_EMPTY,
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
