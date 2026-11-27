// The Chat lab's scenes: the Chat page over a world of fixtures each (worlds.ts), and for what no address opens (a
// menu, a list in it, the memories, a dialog) the clicks that open it. The same list draws the lab's index and is what
// a screenshot of every scene walks; a host adds scenes of its own (ChatLab's `more`).
import type { LabStep } from '@/ui/lab/steps';
import { AT_WORK_IDS, AT_WORK_SCENARIOS, SCENARIO_IDS } from '../fixtures/atWorkScenarios';
import { MORROW_SITE_HISTORY, MORROW_SITE_OPERATIONS } from '../fixtures/morrowSiteThread';
import { PLAN_LINKS_HISTORY } from '../fixtures/planLinksThread';
import { TEAM_HISTORY } from '../fixtures/agentTeamThread';
import { approvalScene, buildScene } from './cardScenes';
import { CHANNEL_TURN_HISTORY, CHANNELS_HISTORY, FILES, MEMORIES, WORKING } from './threads';
import type { ChatWorld } from './worlds';

export interface ChatScene {
    id: string;
    title: string;
    group: 'The page' | 'Threads' | 'Cards' | 'A turn at work' | 'The Beside' | 'Memories' | 'Connect' | 'The composer';
    world: ChatWorld;
    /** More of the address the page reads (the Beside's helper column, `watch`). */
    place?: Record<string, string>;
    steps?: LabStep[];
}

/** A short conversation, for scenes about what's around the thread. */
const BRIEF = { history: CHANNELS_HISTORY.slice(0, 2) };
const CONNECT: LabStep = { click: '[data-testid="connect-menu-button"]' };
const ADD: LabStep = { click: '[data-testid="composer-add-button"]' };
const MEMORIES_BUTTON: LabStep = { button: 'Memories' };

export const SCENES: readonly ChatScene[] = [
    { id: 'start', title: 'Start: nothing said yet', group: 'The page', world: {} },
    { id: 'loading', title: 'Loading the conversation', group: 'The page', world: { session: 'hangs' } },
    { id: 'load-error', title: 'The conversation didn’t load', group: 'The page', world: { session: 'refused' } },
    { id: 'gated', title: 'No NoClick on this account', group: 'The page', world: { missing: true } },

    { id: 'channels', title: 'Texted, called and emailed turns, NoClick’s notes, a space’s news, a setup card, a file it made', group: 'Threads', world: { history: CHANNELS_HISTORY } },
    { id: 'plan-links', title: 'Plan sign-in links (a long turn’s cards)', group: 'Threads', world: { history: PLAN_LINKS_HISTORY } },
    { id: 'morrow-site', title: 'A site built, deployed and checked', group: 'Threads', world: { history: MORROW_SITE_HISTORY, operations: MORROW_SITE_OPERATIONS } },
    { id: 'agent-team', title: 'An agent team and its channel', group: 'Threads', world: { history: TEAM_HISTORY, team: true } },
    { id: 'channel-turn', title: 'A channel’s turn: an account to connect', group: 'Threads', world: { history: CHANNEL_TURN_HISTORY } },

    { id: 'build-asking', title: 'An automation being built, waiting on its question', group: 'Cards', world: buildScene('asking') },
    { id: 'build-done', title: 'An automation built, its app published', group: 'Cards', world: buildScene('done') },
    { id: 'approval-purchase', title: 'A purchase waiting for your OK', group: 'Cards', world: approvalScene('purchase') },
    { id: 'approval-deletion', title: 'A deletion waiting for your OK', group: 'Cards', world: approvalScene('deletion') },
    { id: 'agent-for-apps-waiting', title: 'An agent from an agents page, waiting on Roblox and a model', group: 'Cards', world: { agentForApps: 'waiting' } },
    { id: 'agent-for-apps-ready', title: 'An agent from an agents page, with everything connected', group: 'Cards', world: { agentForApps: 'ready' } },

    { id: 'working', title: 'A turn at work: Stop', group: 'A turn at work', world: WORKING },
    { id: 'steer', title: 'A turn at work: Steer', group: 'A turn at work', world: WORKING, steps: [{ type: '[data-testid="coordinator-home"] textarea', text: 'And a contact form?' }] },

    ...SCENARIO_IDS.map((id): ChatScene => ({ id: `beside-${id}`, title: `Beside: ${AT_WORK_SCENARIOS[id].title}`, group: 'The Beside', world: { beside: id } })),
    { id: 'beside-watch', title: 'Beside: a helper’s conversation open beside the chat', group: 'The Beside', world: { beside: 'one' }, place: { watch: AT_WORK_IDS.LARKSPUR_CODER } },
    { id: 'beside-review', title: 'Beside: Review open on a held purchase', group: 'The Beside', world: { beside: 'busy' }, steps: [{ button: 'Review' }] },

    { id: 'memories', title: 'Memories', group: 'Memories', world: { ...BRIEF, memories: MEMORIES }, steps: [MEMORIES_BUTTON] },
    { id: 'memory-open', title: 'A memory open', group: 'Memories', world: { ...BRIEF, memories: MEMORIES }, steps: [MEMORIES_BUTTON, { click: '[data-testid="memory-entry"]' }] },
    { id: 'memory-edit', title: 'A memory being edited', group: 'Memories', world: { ...BRIEF, memories: MEMORIES }, steps: [MEMORIES_BUTTON, { click: '[data-testid="memory-entry"]' }, { button: 'Edit memory' }] },

    { id: 'connect', title: 'Connect', group: 'Connect', world: BRIEF, steps: [CONNECT] },
    { id: 'connect-whatsapp', title: 'Connect: WhatsApp', group: 'Connect', world: BRIEF, steps: [CONNECT, { button: 'WhatsApp', laptop: true }] },
    { id: 'connect-imessage', title: 'Connect: iMessage', group: 'Connect', world: BRIEF, steps: [CONNECT, { button: 'iMessage', laptop: true }] },
    { id: 'connect-email', title: 'Connect: email', group: 'Connect', world: BRIEF, steps: [CONNECT, { button: 'Email' }] },
    { id: 'connect-mcp', title: 'Connect: MCP', group: 'Connect', world: BRIEF, steps: [CONNECT, { button: 'MCP' }] },

    { id: 'add', title: 'The “+” menu', group: 'The composer', world: BRIEF, steps: [ADD] },
    { id: 'add-files', title: 'The “+” menu: your files', group: 'The composer', world: { ...BRIEF, files: FILES }, steps: [ADD, { button: 'Add from your files' }] },
    { id: 'add-automations', title: 'The “+” menu: automations', group: 'The composer', world: BRIEF, steps: [ADD, { button: 'Point at an automation' }] },
    { id: 'add-accounts', title: 'The “+” menu: accounts', group: 'The composer', world: BRIEF, steps: [ADD, { button: 'All accounts' }] },
    { id: 'model', title: 'The model picker', group: 'The composer', world: BRIEF, steps: [{ click: 'button[aria-label^="Model:"]' }] },
    { id: 'account', title: 'The account it runs on', group: 'The composer', world: BRIEF, steps: [{ click: '[data-testid="coordinator-composer-footer"] button[aria-label^="Runs on:"]' }] },
    { id: 'clear', title: 'Clearing the session, confirmed', group: 'The composer', world: BRIEF, steps: [ADD, { button: 'Clear for everyone…' }] },
];

/** A scene's address in the lab: the scene, then what more the page reads. */
export const sceneSearch = (scene: ChatScene) => `?${new URLSearchParams({ scene: scene.id, ...scene.place })}`;
