// The Usage lab's scenes: the page over a world each (world.ts), at the address it reads ("Where it goes": `by`, `in`,
// `pick`), and for what no address opens (a service over the charges, a charge's drawer, a search) the clicks that open
// it. A host adds scenes of its own (NoClick's app: its sidebar's preview of an account), each drawn its own way. The
// same list draws the lab's index and is what a screenshot of every scene walks.
import type { ReactNode } from 'react';
import type { LabStep } from '@/ui/lab/steps';
import type { BilledAccount, UsageWorld } from './world';

export interface UsageScene {
    id: string;
    title: string;
    group: string;
    world: UsageWorld;
    /** The page's own address: the breakdown's tab (`by`), the drill (`in`) and the row picked at its bottom (`pick`). */
    place?: { by?: string; in?: string; pick?: string };
    steps?: LabStep[];
    /** What a host's own scene draws in place of the page, over the same world. */
    draw?: () => ReactNode;
}

const SONNET = 'openrouter/anthropic/claude-sonnet-4.6';
const INSIDE_SONNET = `service:ai,item:${encodeURIComponent(SONNET)}`;
const MEMBER: UsageWorld = { billed: 'member' };
const TEAM: UsageWorld = { billed: 'team' };
const CHARGE_ROW: LabStep = { click: 'section[aria-label="Charges"] [role="row"][tabindex="0"]' };

const billed = (account: BilledAccount, title: string): UsageScene => ({ id: `account-${account}`, title, group: 'Billed accounts', world: { billed: account } });

export const SCENES: readonly UsageScene[] = [
    billed('member', 'Member, mid-month: agents, a phone line, a site and a domain, auto top-up on'),
    billed('free-new', 'New on Free, five days in: the daily dollar bites'),
    billed('running-out', 'About to run out: $2 left at $4 a day'),
    billed('debt', 'Owes money: a declined top-up and a long call'),
    billed('workspace', 'A workspace of four, its owner paying'),
    billed('team', 'A team naming its work: each charge for whom, and in which workstream'),
    billed('legacy', 'On an old plan: credits read as dollars'),
    billed('platform', 'The developer platform: keys, users and agents'),

    { id: 'by-automation', title: 'By automation', group: 'Where it goes', world: MEMBER, place: { by: 'automation' } },
    { id: 'by-agent', title: 'By agent', group: 'Where it goes', world: MEMBER, place: { by: 'agent' } },
    { id: 'by-site', title: 'By site', group: 'Where it goes', world: MEMBER, place: { by: 'app' } },
    { id: 'by-person', title: 'By person, in a workspace of four', group: 'Where it goes', world: { billed: 'workspace' }, place: { by: 'person' } },
    { id: 'inside-ai', title: 'Inside AI models: each model and what used it', group: 'Where it goes', world: MEMBER, place: { in: 'service:ai' } },
    { id: 'inside-a-model', title: 'Inside one model: what used it', group: 'Where it goes', world: MEMBER, place: { in: INSIDE_SONNET } },
    { id: 'a-model-picked', title: 'One model’s automation picked', group: 'Where it goes', world: MEMBER, place: { in: INSIDE_SONNET, pick: 'workflow:wf_support' } },
    { id: 'inside-an-automation', title: 'Inside an automation: its services', group: 'Where it goes', world: MEMBER, place: { by: 'automation', in: 'automation:wf_support' } },
    { id: 'inside-a-site', title: 'Inside a site', group: 'Where it goes', world: MEMBER, place: { by: 'app', in: 'app:prj_site' } },
    { id: 'inside-a-person', title: 'Inside a person’s work', group: 'Where it goes', world: { billed: 'workspace' }, place: { by: 'person', in: 'person:u_sam' } },
    { id: 'inside-a-platform-agent', title: 'Inside a platform agent', group: 'Where it goes', world: { billed: 'platform' }, place: { by: 'agent', in: 'agent:agt_concierge' } },
    { id: 'by-workstream', title: 'By workstream, the work a team’s agents named', group: 'Where it goes', world: TEAM, place: { by: 'workstream' } },
    { id: 'inside-a-workstream', title: 'Inside a workstream, one merged into it included', group: 'Where it goes', world: TEAM, place: { by: 'workstream', in: 'workstream:ws_launch' } },

    { id: 'charges-one-service', title: 'One service over the charges', group: 'The charges', world: MEMBER, steps: [{ button: 'Calls and texts' }] },
    { id: 'charge-drawer', title: 'A charge’s drawer: what it was for and how it was priced', group: 'The charges', world: MEMBER, steps: [CHARGE_ROW] },
    { id: 'charge-in-a-workstream', title: 'A teammate’s charge in a workstream: who it was for, and which', group: 'The charges', world: TEAM, steps: [{ type: 'input[aria-label="Search charges"]', text: 'Spring launch' }, CHARGE_ROW] },
    { id: 'charges-no-match', title: 'A search that finds nothing', group: 'The charges', world: MEMBER, steps: [{ type: 'input[aria-label="Search charges"]', text: 'zzzz' }] },

    { id: 'unbilled', title: 'What each thing cost, where nobody is billed', group: 'Nobody billed', world: { unbilled: 'busy' } },
    { id: 'unbilled-inside-ai', title: 'Inside AI models, where nobody is billed', group: 'Nobody billed', world: { unbilled: 'busy' }, place: { in: 'service:ai' } },
    { id: 'unbilled-charge-drawer', title: 'A charge’s drawer, where nobody is billed', group: 'Nobody billed', world: { unbilled: 'busy' }, steps: [CHARGE_ROW] },
    { id: 'unbilled-empty', title: 'Nothing charged yet', group: 'Nobody billed', world: { unbilled: 'empty' } },
    { id: 'loading', title: 'Still reading', group: 'Nobody billed', world: { read: 'waiting' } },
    { id: 'failed', title: 'The read failed', group: 'Nobody billed', world: { read: 'failed' } },
];

/** A scene's address in the lab: its id, and the page's own place beside it. */
export function sceneSearch(scene: UsageScene): string {
    const params = new URLSearchParams({ scene: scene.id });
    for (const [key, value] of Object.entries(scene.place ?? {})) if (value) params.set(key, value);
    return `?${params}`;
}
