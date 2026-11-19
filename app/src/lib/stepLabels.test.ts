import { beforeAll, describe, expect, it } from 'vitest';
import type { SerializedNodeMeta } from '@/lib/nodeCatalogTypes';
import { setNodeIconData } from '@/lib/nodeIconRegistry';
import { kindVerb, stepLine, stepName, verbPhrase, type StepPhase } from './stepLabels';

/** An app as the node catalog the host hands in names it. */
const app = (type: string, label: string): SerializedNodeMeta => ({ type, label, description: '', iconColor: '', iconHtml: '', dimensions: { width: 90, height: 90, iconSize: 40 } });

// The chat names an app the way the app does, from the node catalog the host hands in.
beforeAll(() =>
    setNodeIconData(
        Object.fromEntries(
            [
                app('automation-google-drive', 'Google Drive'),
                app('automation-slack', 'Slack'),
                app('automation-gmail', 'Gmail'),
                app('automation-hackernews', 'Hacker News'),
                app('automation-linear', 'Linear'),
                app('automation-instagram', 'Instagram'),
            ].map((meta) => [meta.type, meta])
        )
    )
);

/** A call's line as the chat draws it. */
function line(tool: string, args: Record<string, unknown>, phase: StepPhase = 'done'): string {
    const { head, tail } = stepLine(stepName(tool, args, phase));
    return `${head}${tail ?? ''}`.replace(/\u00a0/g, ' ');
}

describe('verbPhrase', () => {
    it('inflects an action for running and done, by rule', () => {
        expect(verbPhrase('List Workflows', 'running')).toBe('Listing workflows');
        expect(verbPhrase('List Workflows', 'done')).toBe('Listed workflows');
        expect(verbPhrase('Create Project', 'running')).toBe('Creating project');
        expect(verbPhrase('Commit Files', 'done')).toBe('Committed files');
        expect(verbPhrase('Stop Machine', 'done')).toBe('Stopped machine');
        expect(verbPhrase('Deploy', 'done')).toBe('Deployed');
        expect(verbPhrase('Retry Delivery', 'done')).toBe('Retried delivery');
        expect(verbPhrase('Get Run', 'base')).toBe('Read run');
    });

    it('says what the API calls Get, Put or Fetch the way people do, irregular verbs included', () => {
        expect(verbPhrase('Get Run', 'running')).toBe('Reading run');
        expect(verbPhrase('Get Run', 'done')).toBe('Read run');
        expect(verbPhrase('Fetch a doc or object', 'done')).toBe('Read a doc or object');
        expect(verbPhrase('Put Secret', 'done')).toBe('Saved secret');
        expect(verbPhrase('Buy Number', 'done')).toBe('Bought number');
        expect(verbPhrase('Send Message', 'done')).toBe('Sent message');
    });

    it('starts at the first verb, spells acronyms, and leaves a name with none as it is', () => {
        expect(verbPhrase('credential place call', 'running')).toBe('Placing call');
        expect(verbPhrase('Dns Records', 'running')).toBe('DNS records');
        expect(verbPhrase('Search NoClick', 'running')).toBe('Searching NoClick');
        expect(verbPhrase('Delete, cancel or revoke', 'running')).toBe('Deleting, canceling or revoking');
    });
});

describe('stepName', () => {
    it('names an API call by its operation’s summary, with what it named', () => {
        expect(stepName('noclick__api_call', { operation: 'workflows_list', arguments: { name: 'coordinator' } }, 'running')).toEqual({
            label: 'Listing workflows',
            detail: 'coordinator',
            kind: 'read',
        });
        expect(stepName('noclick__api_call', { operation: 'projects_deployments_create', arguments: { project_id: 'id_1' } }, 'done')).toEqual({
            label: 'Deployed',
            detail: undefined,
            kind: 'write',
        });
        expect(line('noclick__api_call', { operation: 'workflows_list', arguments: { name: 'coordinator' } })).toBe('Listed workflows · coordinator');
    });

    it('says NoClick finding its way as looking into it: what it looked up, how to do something, the doc it read', () => {
        // The agent's thread names NoClick's own tools bare.
        for (const tool of ['noclick__search', 'search']) {
            expect(line(tool, { query: 'failed runs' }, 'running')).toBe('Looking up “failed runs”');
            expect(line(tool, { query: 'create app deploy repo static publish website' })).toBe('Looked up “create app deploy repo static publish website”');
            expect(stepName(tool, { query: 'failed runs' }, 'done')).toMatchObject({ label: 'Looked into it', kind: 'search' });
        }
        expect(line('noclick__search', { kind: 'object', query: '24247075-695e-479b-a817-c510073fba40' }, 'running')).toBe('Looking into it');
        expect(line('noclick__api_describe', { operation: 'workflows_runs_get', detail: 'full' }, 'running')).toBe('Checking how to get a run');
        expect(line('api_describe', { operation: 'workflows_list' })).toBe('Checked how to list workflows');
        expect(line('noclick__api_describe', { query: 'list workflows in account' })).toBe('Looked up “list workflows in account”');
        expect(line('noclick__fetch', { id: 'guide:apps#create-an-app' })).toBe('Read the apps guide');
        expect(line('fetch', { id: 'workflow:24247075-695e-479b-a817-c510073fba40' }, 'running')).toBe('Reading a workflow');
    });

    it('says what a service NoClick picks and pays for did, never its name', () => {
        expect(line('exa__search', { query: 'site:developers.openai.com/codex/mcp "codex mcp add"' })).toBe(
            'Searched the web for “site:developers.openai.com/codex/mcp "codex mcp add"”'
        );
        expect(line('exa__search', { query: 'codex mcp' }, 'running')).toBe('Searching the web for “codex mcp”');
        expect(line('exa__get_contents', { urls: 'https://github.com/openai/codex/blob/main/docs/config.md', include_text: 'true' })).toBe(
            'Read github.com/openai/codex/blob/main/docs/config.md'
        );
        expect(line('exa__get_contents', { urls: ['https://www.noclick.com/pricing/', 'https://noclick.com/'] })).toBe('Read noclick.com/pricing and 1 more');
        expect(line('exa__answer', { query: 'Who maintains the Codex CLI?' })).toBe('Researched “Who maintains the Codex CLI?”');
        expect(line('perplexity__chat_completion', { prompt: 'Compare pgvector and Pinecone' }, 'running')).toBe('Researching “Compare pgvector and Pinecone”');
        expect(stepName('exa__search', {}, 'done')).toEqual({ label: 'Searched the web', kind: 'search' });
        expect(stepName('exa__get_contents', {}, 'base').label).toBe('Read a web page');
    });

    it('names an app the person connected the way the app does, said as a sentence', () => {
        expect(line('google_drive__search_files', { query: "mimeType contains 'image/'", page_size: 100 })).toBe(
            "Searched Google Drive files for “mimeType contains 'image/'”"
        );
        expect(line('slack__search_workspace_messages', { query: 'from:levi after:2026-10-15', count: 25 })).toBe(
            'Searched Slack workspace messages for “from:levi after:2026-10-15”'
        );
        expect(line('gmail__fetch_email_thread', { thread_id: '1a14994908f8649b', format: 'full' })).toBe('Read an email thread in Gmail');
        expect(line('gmail__fetch_email_message', { message_id: '1a14994908f8649b' }, 'running')).toBe('Reading an email message in Gmail');
        expect(line('hackernews__fetch_newest_stories', { limit: 5, fetch_details: true })).toBe('Read the newest Hacker News stories');
        expect(line('linear__create_issue', { title: 'Fix login' })).toBe('Created an issue in Linear · Fix login');
        expect(line('slack__list_teams', {})).toBe('Listed Slack teams');
        expect(line('slack__list_custom_emoji', {})).toBe('Listed Slack custom emoji');
        // A platform-keyed operation another service performs still names the site it read.
        expect(line('instagram__scrape_profile_metadata', { usernames: 'noclick' })).toBe('Read Instagram profile metadata');
        expect(stepName('gmail__fetch_email_thread', {}, 'base').label).toBe('Read an email thread in Gmail');
    });

    it('says recalling as checking what it remembers, and finding an app as looking for one', () => {
        for (const tool of ['memory__search', 'search_memories']) {
            expect(line(tool, { query: 'reach me' }, 'running')).toBe('Checking what it remembers about “reach me”');
            expect(stepName(tool, {}, 'done')).toMatchObject({ label: 'Checked what it remembers', kind: 'search' });
        }
        expect(line('search_credential_tools', { query: 'place a phone call' })).toBe('Looked for an app for “place a phone call”');
        expect(stepName('search_credential_tools', {}, 'done').label).toBe('Looked for the right app');
    });

    it('says a browser’s calls as what happens on the page, by its address and never the browser’s id', () => {
        const browserId = '4c1e7a2b-9d3f-4e6a-8b5c-2f1d0e9a7b63';
        const goto = { operation: 'browsers_goto', arguments: { browser_id: browserId, url: 'https://www.kestrel.example/pricing' } };
        expect(line('noclick__api_call', goto, 'running')).toBe('Opening kestrel.example/pricing');
        expect(line('noclick__api_call', goto)).toBe('Opened kestrel.example/pricing');
        expect(line('noclick__api_call', { operation: 'browsers_content', arguments: { browser_id: browserId } }, 'running')).toBe('Reading the page');
        expect(line('noclick__api_call', { operation: 'browsers_extract', arguments: { browser_id: browserId, query: 'the price' } })).toBe('Read off the page “the price”');
        expect(line('noclick__api_call', { operation: 'browsers_create', arguments: { timeout_s: 120 } }, 'running')).toBe('Starting a browser');
        expect(line('noclick__api_call', { operation: 'browsers_act', arguments: { browser_id: browserId, instruction: 'Add the blue mug to the cart' } }, 'running')).toBe(
            'Running a task in the browser · Add the blue mug to the cart'
        );
        // An agent's own browser tool reads the same.
        expect(line('browser__goto', { url: 'https://kestrel.example/' }, 'running')).toBe('Opening kestrel.example');
        expect(line('mcp__noclick__browser__content', {})).toBe('Read the page');
        expect(line('mcp__nc__browser__content', {})).toBe('Read the page');  // a hosted sandbox's NoClick tools
        for (const [tool, args] of [['noclick__api_call', goto], ['browser__goto', { url: 'https://kestrel.example/' }]] as const) {
            expect(JSON.stringify(stepName(tool, args, 'running'))).not.toContain(browserId);
        }
    });

    it('names any other tool by its own name: a namespace dropped, a hash ignored', () => {
        expect(stepName('find_connections', { query: 'Gmail' }, 'done')).toMatchObject({ label: 'Found connections', detail: 'Gmail' });
        expect(stepName('credential_place_call_4e02f2cc2e', {}, 'running')).toMatchObject({ label: 'Placing call', kind: 'outbound' });
        expect(stepName('request_build', { name: 'Email Draft Assistant' }, 'running').label).toBe('Requesting build');
        expect(stepName('memory__read', { name: 'plan' }, 'done')).toMatchObject({ label: 'Read memory', detail: 'plan' });
    });

    it('says long work by its kind’s action, and nothing when the kind names none', () => {
        expect(kindVerb('project.deploy', 'done')).toBe('Deployed');
        expect(kindVerb('project.deploy', 'base')).toBe('Deploy');
        expect(kindVerb('workflow.build', 'done')).toBe('Built');
        expect(kindVerb('agent.turn', 'done')).toBeUndefined();
    });
});
