// The Connections lab's scenes: the page over a world each (../fixtures/world.ts), at the address it reads (`view`,
// `account`), and for what no address opens (a search, a dialog, a menu) the clicks that open it. The same list draws
// the lab's index and is what a screenshot of every scene walks; a host adds scenes of its own.
import type { LabStep } from '@/ui/lab/steps';
import type { ConnectionsWorld } from '../fixtures/world';

export interface ConnectionsScene {
    id: string;
    title: string;
    group: 'All apps' | 'Tabs' | 'An account' | 'Its proof' | 'Dialogs';
    world: ConnectionsWorld;
    /** The page's own address: its tab (`view`) and the account it opens (`account`). */
    place?: { view?: string; account?: string };
    steps?: LabStep[];
}

const GITHUB = { view: 'connected', account: 'cred_github' };
const SEARCH: LabStep = { type: 'input[type="search"]', text: '' };
const MENU: LabStep = { press: '[aria-label^="More for "]' };

/** GitHub's page with its provider saying `probe`. */
const proof = (id: string, title: string, probe: NonNullable<ConnectionsWorld['probes']>[string]): ConnectionsScene => ({
    id: `proof-${id}`,
    title,
    group: 'Its proof',
    world: { probes: { cred_github: probe } },
    place: GITHUB,
});

export const SCENES: readonly ConnectionsScene[] = [
    { id: 'catalog', title: 'Every app and AI company: connected, broken and not yet', group: 'All apps', world: {} },
    { id: 'catalog-first-run', title: 'Nothing connected yet', group: 'All apps', world: { accounts: [] } },
    { id: 'catalog-search', title: 'A search across apps and AI companies (“google”)', group: 'All apps', world: {}, steps: [{ ...SEARCH, text: 'google' }] },
    { id: 'catalog-no-match', title: 'A search that finds nothing', group: 'All apps', world: {}, steps: [{ ...SEARCH, text: 'zzqx' }] },

    { id: 'connected', title: 'Connected: yours, broken first', group: 'Tabs', world: {}, place: { view: 'connected' } },
    { id: 'connected-search', title: 'Connected, searched (“gmail”)', group: 'Tabs', world: {}, place: { view: 'connected' }, steps: [{ ...SEARCH, text: 'gmail' }] },
    { id: 'connected-loading', title: 'Connected, still loading', group: 'Tabs', world: { accounts: 'waiting' }, place: { view: 'connected' } },
    { id: 'connected-empty', title: 'Connected, with nothing yet', group: 'Tabs', world: { accounts: [] }, place: { view: 'connected' } },
    { id: 'workspace', title: 'Workspace: accounts shared with the team', group: 'Tabs', world: {}, place: { view: 'organization' } },
    { id: 'workspace-empty', title: 'Workspace, with nothing shared', group: 'Tabs', world: { accounts: ['gmail', 'github'] }, place: { view: 'organization' } },
    { id: 'shared', title: 'Shared with me', group: 'Tabs', world: {}, place: { view: 'shared' } },
    { id: 'shared-empty', title: 'Shared with me, with nothing', group: 'Tabs', world: { accounts: ['gmail'] }, place: { view: 'shared' } },
    { id: 'own-workspace', title: 'The account’s own workspace: no Workspace tab', group: 'Tabs', world: { team: null }, place: { view: 'connected' } },

    { id: 'account', title: 'Working, used by an automation', group: 'An account', world: {}, place: GITHUB },
    { id: 'account-two-of-an-app', title: 'A second account of the same app', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_gmail_ops' } },
    { id: 'account-revoked', title: 'Disconnected: Reconnect', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_slack' } },
    { id: 'account-broken', title: 'The connection dropped, and its provider turns it down', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_discord' } },
    { id: 'account-over-cap', title: 'An account with nothing of its own to show (reachability)', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_stripe' } },
    { id: 'account-moved', title: 'Brought over by an agent’s move', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_linear' } },
    { id: 'account-shared-with-me', title: 'Shared with me by a teammate', group: 'An account', world: {}, place: { view: 'shared', account: 'cred_notion' } },
    { id: 'account-workspace', title: 'The workspace’s (team-shared)', group: 'An account', world: {}, place: { view: 'organization', account: 'cred_hubspot' } },
    { id: 'account-ai-key', title: 'An AI company’s API key', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_anthropic' } },
    { id: 'account-ai-plan', title: 'An AI plan’s sign-in', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_claude_plan' } },
    { id: 'account-whatsapp', title: 'A WhatsApp number', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_whatsapp' } },
    { id: 'account-gone', title: 'An account no longer there', group: 'An account', world: {}, place: { view: 'connected', account: 'cred_gone' } },

    proof('signed-in', 'Working: who it signs in as, nothing to list', { reachable: true, samples: [], account_label: 'maya-n' }),
    proof('reachability', 'Working: the key was accepted, nothing account-specific', { reachable: true, samples: [], proves: 'reachability' }),
    proof('answered', 'Working: the provider answered', { reachable: true }),
    proof('refused-hint', 'Turned down, with what to do and the provider’s reply', { reachable: false, hint: 'GitHub no longer accepts this sign-in. Reconnect it.', error: 'Bad credentials (401)' }),
    proof('refused', 'Turned down, in the provider’s words alone', { reachable: false, error: 'Bad credentials (401)' }),
    proof('unverified', 'No clear answer', { reachable: null }),
    proof('failed', 'The check itself didn’t go through', 'failed'),
    proof('checking', 'Asking the provider', 'waiting'),

    { id: 'menu', title: 'An account’s menu', group: 'Dialogs', world: {}, place: GITHUB, steps: [MENU] },
    { id: 'renaming', title: 'Renaming an account in place', group: 'Dialogs', world: {}, place: GITHUB, steps: [MENU, { item: 'Rename' }] },
    { id: 'delete', title: 'Deleting an account: what still uses it', group: 'Dialogs', world: {}, place: GITHUB, steps: [MENU, { item: 'Delete account' }] },
    { id: 'remove-moved', title: 'Removing a moved account', group: 'Dialogs', world: {}, place: { view: 'connected', account: 'cred_linear' }, steps: [{ button: 'Remove' }] },
    { id: 'mcp-setup', title: 'Using NoClick from your AI apps', group: 'Dialogs', world: {}, steps: [{ click: 'section.mt-12 > button' }] },
];

/** A scene's address in the lab: its id, then the page's own. */
export function sceneSearch(scene: ConnectionsScene): string {
    return `?${new URLSearchParams({ scene: scene.id, ...scene.place })}`;
}
