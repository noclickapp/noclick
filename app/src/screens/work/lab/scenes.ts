// The lab's scenes: every view of Work, each a place in Work's own address (place.ts) over a world of fixtures
// (worlds.ts), and for what no address opens (the space's menu and its dialogs) the clicks that open it. The same list
// draws the lab's index and is what a screenshot of every view walks.
import { id as agentId } from '../agents/fixtures/workAgents';
import { AGENT_ID } from '../conversation/fixtures/workAgent';
import { IN_USE } from '../profile/fixtures/instructions';
import { ROBLOX_CHANNEL_ID } from '../fixtures/agentForApps';
import { SOCIAL_NOCLICK, SOCIAL_SPACE, TEMPLATE_ADDRESS } from '../templates/fixtures';
import type { LabStep } from '@/ui/lab/steps';
import type { LabWorld } from './worlds';

export interface LabScene {
    id: string;
    title: string;
    group: 'Spaces' | 'Members' | 'Space settings' | 'Agents';
    world: LabWorld;
    /** Work's place: its params as the address keeps them. */
    place: Record<string, string>;
    steps?: LabStep[];
    /** What its steps end on, where that's no menu or dialog: a selector for it. */
    opens?: string;
}

const SPACE = { space: 'ws_noclick' };
/** Home lists every agent of the account. */
const HOME_AGENTS = { space: 'home', show: 'agents' };
const PROFILE = { ...HOME_AGENTS, agent: agentId(1), panel: 'profile' };
const SPACE_MENU: LabStep = { press: '[data-testid="space-menu"]' };
const INSTRUCTIONS_EDIT: LabStep = { click: '[data-testid="agent-instructions"] [data-action="edit"]' };
const EDITED = IN_USE.replace('Answer customers in #support', 'Answer customers in #support and on WhatsApp');

export const SCENES: readonly LabScene[] = [
    { id: 'home', title: 'Home', group: 'Spaces', world: 'spaces', place: SPACE },
    { id: 'channel', title: 'A channel', group: 'Spaces', world: 'spaces', place: { ...SPACE, channel: 'ch_launch' } },
    { id: 'thread', title: 'A thread beside its channel', group: 'Spaces', world: 'spaces', place: { ...SPACE, channel: 'ch_launch', thread: 'l4' } },
    { id: 'threads', title: 'Threads you follow', group: 'Spaces', world: 'spaces', place: { ...SPACE, channel: 'threads' } },
    { id: 'templates', title: 'Templates: NoClick’s gallery', group: 'Spaces', world: 'spaces', place: { ...SPACE, channel: 'templates' } },
    { id: 'template-page', title: 'A template’s page in the gallery', group: 'Spaces', world: 'spaces', place: { ...SPACE, channel: 'templates', listing: 'social-media-team' } },
    { id: 'agent-for-apps-waiting', title: 'An agents page’s agent in its channel, waiting on what it needs', group: 'Spaces', world: 'agent_for_apps', place: { space: 'home', channel: ROBLOX_CHANNEL_ID } },
    { id: 'agent-for-apps-ready', title: 'An agents page’s agent in its channel, saying hello', group: 'Spaces', world: 'agent_for_apps_ready', place: { space: 'home', channel: ROBLOX_CHANNEL_ID } },
    { id: 'template-new', title: 'A space template’s page of asks, as a new space', group: 'Spaces', world: 'spaces', place: { space: 'home', template: TEMPLATE_ADDRESS } },
    { id: 'template-into', title: 'A space template’s page of asks, into a space you have', group: 'Spaces', world: 'spaces', place: { ...SPACE, template: TEMPLATE_ADDRESS, into: 'ws_noclick' } },
    { id: 'template-welcome', title: 'A space template just added: its #noclick welcome post', group: 'Spaces', world: 'template_added', place: { space: SOCIAL_SPACE, channel: SOCIAL_NOCLICK } },
    { id: 'dms', title: 'DMs', group: 'Spaces', world: 'spaces', place: { ...SPACE, show: 'dms' } },
    { id: 'dm', title: 'A DM', group: 'Spaces', world: 'spaces', place: { ...SPACE, show: 'dms', channel: 'dm_priya' } },
    { id: 'resources', title: 'Resources', group: 'Spaces', world: 'spaces', place: { ...SPACE, show: 'resources' } },
    { id: 'resources-item', title: 'A shared resource', group: 'Spaces', world: 'spaces', place: { ...SPACE, show: 'resources', res: 'code', item: 'code:rep_site' } },
    { id: 'resources-automations', title: 'Automations in a space', group: 'Spaces', world: 'spaces', place: { ...SPACE, show: 'resources', res: 'automations' } },
    { id: 'resources-automation', title: 'An automation in a space', group: 'Spaces', world: 'spaces', place: { ...SPACE, show: 'resources', res: 'automations', item: 'automations:wf_monday_plan' } },
    { id: 'members-people', title: 'Members: people', group: 'Members', world: 'spaces', place: { ...SPACE, panel: 'people' } },
    { id: 'members-agents', title: 'Members: agents', group: 'Members', world: 'spaces', place: { ...SPACE, panel: 'agents' } },
    { id: 'members-access', title: 'Members: what they reach', group: 'Members', world: 'spaces', place: { ...SPACE, panel: 'access' } },
    { id: 'space-menu', title: 'The space’s menu', group: 'Space settings', world: 'spaces', place: SPACE, steps: [SPACE_MENU] },
    { id: 'space-edit', title: 'Name and logo', group: 'Space settings', world: 'spaces', place: SPACE, steps: [SPACE_MENU, { item: 'Name and logo' }] },
    { id: 'space-archive', title: 'Archive the space', group: 'Space settings', world: 'spaces', place: SPACE, steps: [SPACE_MENU, { item: 'Archive space' }] },
    { id: 'space-delete', title: 'Delete the space', group: 'Space settings', world: 'spaces', place: SPACE, steps: [SPACE_MENU, { item: 'Delete space' }] },
    { id: 'agents', title: 'Agents', group: 'Agents', world: 'agents', place: HOME_AGENTS },
    { id: 'session', title: 'A session, with what works beside it', group: 'Agents', world: 'session', place: { ...HOME_AGENTS, agent: AGENT_ID } },
    { id: 'profile', title: 'Profile', group: 'Agents', world: 'agents', place: PROFILE },
    {
        id: 'profile-instructions',
        title: 'Profile: its instructions',
        group: 'Agents',
        world: 'agents',
        place: PROFILE,
        steps: [{ button: 'Show all' }],
        opens: '[data-testid="instructions-history"] li',
    },
    {
        id: 'profile-instructions-edit',
        title: 'Profile: editing its instructions',
        group: 'Agents',
        world: 'agents',
        place: PROFILE,
        steps: [INSTRUCTIONS_EDIT],
        opens: '[data-testid="instructions-edit"] textarea:not([disabled])',
    },
    {
        id: 'profile-instructions-version',
        title: 'Profile: what a version of its instructions changed',
        group: 'Agents',
        world: 'agents',
        place: PROFILE,
        steps: [{ button: 'Show all' }, { click: '[data-testid="instructions-history"] li:nth-child(2) button[aria-expanded]' }],
        opens: '[data-testid="instructions-history"] [data-testid="diff"]',
    },
    {
        id: 'profile-instructions-changed',
        title: 'Profile: its instructions changed while you edit',
        group: 'Agents',
        world: 'agents_raced',
        place: PROFILE,
        steps: [INSTRUCTIONS_EDIT, { type: '[data-testid="instructions-edit"] textarea:not([disabled])', text: EDITED }, { button: 'Save' }],
        opens: '[data-testid="instructions-changed"]',
    },
    { id: 'profile-triggers', title: 'Profile: triggers', group: 'Agents', world: 'agents', place: { ...PROFILE, ptab: 'triggers' } },
    { id: 'profile-tools', title: 'Profile: tools', group: 'Agents', world: 'agents', place: { ...PROFILE, ptab: 'tools' } },
    { id: 'profile-files', title: 'Profile: files', group: 'Agents', world: 'agents', place: { ...PROFILE, ptab: 'files' } },
    { id: 'profile-activity', title: 'Profile: activity', group: 'Agents', world: 'agents', place: { ...PROFILE, ptab: 'activity' } },
    { id: 'new-agent', title: 'A new agent', group: 'Agents', world: 'agents', place: { ...HOME_AGENTS, agent: 'new' } },
    { id: 'machine', title: 'An agent’s machine', group: 'Agents', world: 'agents', place: { ...HOME_AGENTS, agent: agentId(1), machine: '1' } },
];

/** A scene's address in the lab: the scene, then Work's place. */
export const sceneSearch = (scene: LabScene) => `?${new URLSearchParams({ scene: scene.id, ...scene.place })}`;
