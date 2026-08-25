/* Descriptions and lookup helpers for the supported CLI agent harnesses.
   The harness-to-model contract lives in ~/lib/agentModelMatch; this file
   owns only public display metadata. */

import { HARNESS_MODEL_SPECS } from '~/lib/agentModelMatch';
import type { HarnessContent } from './types';

export type { HarnessContent, HarnessFaq } from './types';

/** Date the harness content was last revised — used for sitemap <lastmod>. */
export const HARNESSES_LASTMOD = '2026-07-10';

const HARNESS_LIST: HarnessContent[] = [
    {
        modelType: 'claude_code',
        slug: 'claude-code',
        displayName: 'Claude Code',
        vendor: 'Anthropic',
        tagline: "Anthropic's agentic coding CLI, wired to the apps your business runs on.",
        intro:
            "Claude Code is Anthropic's command-line coding agent. A self-hosted NoClick installation runs the operator’s installed CLI and connects integrations to its tools handle. Wire in an integration and Claude Code can read and act on Slack, Linear, your database, and more on its own, calling each one as a tool while it works. It is the same capable agent, connected to your actual workflows.",
        strengths: [
            'Careful multi-step planning before it acts',
            'Reliable on long, structured tasks',
            'Reads context thoroughly before making changes',
            'Comfortable across code, data, and APIs',
        ],
        whenToUse:
            'Reach for Claude Code when you want a careful, capable agent that plans before it acts and can carry a multi-step task across several connected tools.',
        accentColor: 'text-orange-400',
        faqs: [
            {
                question: 'What does it mean to connect an app to Claude Code?',
                answer: "You wire an integration node into the agent's tools handle. Each operation that app exposes becomes a tool Claude Code can call directly, so it can take real actions in that app instead of only describing them.",
            },
            {
                question: 'Do I need to write any code to set this up?',
                answer: 'No. You pick the integrations, click to open the agent in NoClick, connect your accounts, and the tools are ready. There is no glue code to maintain.',
            },
            {
                question: 'Does Claude Code run on my own machine?',
                answer: 'Yes. Install and authenticate the CLI on the machine serving NoClick; schedules and triggers can start it while that backend is running.',
            },
            {
                question: 'Can Claude Code use more than one app in a single run?',
                answer: 'Yes. Wire as many integrations into the same agent as you need and it can use all of them together while completing a task.',
            },
        ],
    },
    {
        modelType: 'codex',
        slug: 'codex',
        displayName: 'Codex',
        vendor: 'OpenAI',
        tagline: "OpenAI's Codex CLI as a tool-using agent for your whole stack.",
        intro:
            "Codex is OpenAI's command-line coding agent. A self-hosted NoClick installation runs the operator’s CLI and connects apps to it as tools, turning it from a coding assistant into an operator that can act across your systems. Connect an integration to the agent and Codex can query, create, and update records in that app directly. You keep the Codex experience and give it real reach into the tools your team already uses.",
        strengths: [
            'Fast, capable code generation and editing',
            'Good at well-scoped, concrete tasks',
            'Strong at API and data manipulation',
            'Familiar to teams already on OpenAI tooling',
        ],
        whenToUse:
            'Choose Codex when you want a quick, capable agent for concrete tasks that touch one or more connected apps.',
        accentColor: 'text-emerald-400',
        faqs: [
            {
                question: 'How does Codex get access to my apps?',
                answer: "You connect an integration to the agent's tools handle and select which operations to expose. Codex then calls those operations as tools, authenticated with the credentials you connect in NoClick.",
            },
            {
                question: 'Is this the same Codex CLI?',
                answer: 'Yes. Install and authenticate the Codex CLI on the backend machine; NoClick adds your connected apps as tools.',
            },
            {
                question: 'Can I trigger a Codex agent automatically?',
                answer: 'Yes. A running installation can start it from a schedule, a webhook, or another app event, not just by hand.',
            },
            {
                question: 'Which apps can I connect?',
                answer: 'Any of NoClick’s tool-provider integrations, from Slack and Linear to GitHub, Notion, Google Sheets, Postgres, and dozens more.',
            },
        ],
    },
    {
        modelType: 'opencode',
        slug: 'opencode',
        displayName: 'OpenCode',
        vendor: 'OpenCode',
        tagline: 'The open, model-agnostic coding CLI as a connected agent.',
        intro:
            'OpenCode is an open, model-agnostic command-line coding agent. A self-hosted NoClick installation runs the operator’s CLI and adds your apps as tools, so it can act on real systems rather than just edit files. Wire an integration into the agent and OpenCode can use that app’s operations directly while it works. It is a flexible choice when you want an open agent with broad model support and real tool access.',
        strengths: [
            'Open and model-agnostic',
            'Flexible across many underlying models',
            'Good general-purpose tool use',
            'Lightweight to point at a focused task',
        ],
        whenToUse:
            'Pick OpenCode when you want an open, flexible agent and the freedom to choose the underlying model, with your apps wired in as tools.',
        accentColor: 'text-sky-400',
        faqs: [
            {
                question: 'What makes OpenCode different here?',
                answer: 'OpenCode is open and model-agnostic, so you have flexibility over the underlying model. NoClick connects the installed CLI to your apps as tools.',
            },
            {
                question: 'How do I give OpenCode tools?',
                answer: "Connect an integration node to the agent's tools handle and choose the operations to allow. Each becomes a tool the agent can call.",
            },
            {
                question: 'Do I manage any infrastructure?',
                answer: 'Install and authenticate OpenCode on the backend machine; NoClick supplies the credentials you configure for connected apps.',
            },
            {
                question: 'Can it combine several apps?',
                answer: 'Yes. Add as many integrations as you need and the agent can use them together in one run.',
            },
        ],
    },
    {
        modelType: 'openclaw',
        slug: 'openclaw',
        displayName: 'OpenClaw',
        vendor: 'OpenClaw',
        tagline: 'An open CLI agent, connected to your apps as tools.',
        intro:
            'OpenClaw is an open command-line agent. A self-hosted NoClick installation runs the operator’s CLI and connects apps to it as tools, so it can take real actions across your systems. Wire an integration into the agent and OpenClaw can call that app’s operations directly. It is a good fit when you want an open, no-fuss agent with real tool access and operator-managed setup.',
        strengths: [
            'Open and approachable',
            'Simple to point at a task',
            'Solid general tool use',
            'Runs on your own backend machine',
        ],
        whenToUse:
            'Use OpenClaw when you want a straightforward open agent that can act across your connected apps with operator-managed setup.',
        accentColor: 'text-violet-400',
        faqs: [
            {
                question: 'How does OpenClaw act on my apps?',
                answer: "You connect an integration to the agent's tools handle and select operations. OpenClaw calls those operations as tools while it runs.",
            },
            {
                question: 'Is there anything to install?',
                answer: 'Install and authenticate OpenClaw on the machine serving the backend.',
            },
            {
                question: 'Can I run it on a schedule?',
                answer: 'Yes. A running installation can start the agent from a schedule, a webhook, or another app event.',
            },
            {
                question: 'Which apps can it use?',
                answer: 'Any of NoClick’s tool-provider integrations across communication, CRM, developer tools, databases, and more.',
            },
        ],
    },
    {
        modelType: 'hermes_agent',
        slug: 'hermes',
        displayName: 'Hermes',
        vendor: 'Nous Research',
        tagline: 'Nous Research’s Hermes as a tool-using agent in NoClick.',
        intro:
            'Hermes is an open agent built on Nous Research’s Hermes models. A self-hosted NoClick installation runs the operator’s CLI and connects apps to it as tools, so it can do real work across your systems. Wire an integration into the agent and Hermes can use that app’s operations directly while it reasons through a task. It is a strong pick when you want an open-model agent with genuine tool access.',
        strengths: [
            'Built on open Hermes models',
            'Capable general reasoning',
            'Flexible, open-model foundation',
            'Runs with apps wired in as tools',
        ],
        whenToUse:
            'Choose Hermes when you want an open-model agent and want it to act across the apps you connect.',
        accentColor: 'text-rose-400',
        faqs: [
            {
                question: 'What is Hermes here?',
                answer: 'Hermes is an open agent based on Nous Research’s Hermes models. NoClick runs the installed CLI and adds your connected apps as tools.',
            },
            {
                question: 'How do I give Hermes access to an app?',
                answer: "Connect the app's integration node to the agent's tools handle and pick the operations to expose. Each becomes a callable tool.",
            },
            {
                question: 'Do I need my own infrastructure?',
                answer: 'Install and authenticate Hermes on the backend machine; NoClick supplies the credentials you configure for connected apps.',
            },
            {
                question: 'Can Hermes use multiple apps at once?',
                answer: 'Yes. Wire in several integrations and the agent can use them together in a single run.',
            },
        ],
    },
];

/** slug → harness content. */
export const HARNESSES: Record<string, HarnessContent> = Object.fromEntries(
    HARNESS_LIST.map((h) => [h.slug, h]),
);

/** Stable display/order of harnesses (drives the index + sitemap). */
export const HARNESS_ORDER: string[] = HARNESS_LIST.map((h) => h.slug);

export function getHarness(slug: string): HarnessContent | null {
    return HARNESSES[slug] ?? null;
}

export function getAllHarnessSlugs(): string[] {
    return HARNESS_ORDER;
}

/** The data.config.model value to write for a harness slug (from the canonical
    HARNESS_MODEL_SPECS contract). Null if the harness/modelType is unknown. */
export function getHarnessModel(slug: string): string | null {
    const harness = HARNESSES[slug];
    if (!harness) return null;
    return HARNESS_MODEL_SPECS[harness.modelType]?.model ?? null;
}
