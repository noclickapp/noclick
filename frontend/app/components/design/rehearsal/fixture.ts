/* Canned rehearsal runs for iterating on the testing UX without paying a real
   ~15s agent run per look. Structure mirrors how rehearsal data really shapes:
   a TRIGGER carries several staged situations (mocks), because "new email" is
   not one situation — a qualified lead, a one-line inquiry and a newsletter
   should produce visibly different agent behaviour, including the behaviour of
   doing nothing at all.

   Every identity, organisation, address, URL, identifier and event below is
   hand-authored synthetic data. Reserved `.example` domains and NANP's
   555-0100–0199 fiction range make that provenance visible in the values.
   Timings are illustrative and model the rhythm of a representative run.
   Thought rows design ahead of the data — the live rehearsal does not stream
   reasoning yet; this is where the view for it gets built. */

export type Provider = 'gmail' | 'slack' | 'whatsapp' | 'telegram';

export interface ThoughtEvent {
    kind: 'thought';
    at: number;
    text: string;
}

export interface ToolEvent {
    kind: 'tool';
    at: number;
    completeAt: number;
    step: string;
    text: string;
    /** Absent for tools with no provider account — web search, MCP, sandbox. */
    provider?: Provider;
    /** Generic mark when there is no provider: globe / plug / terminal. */
    glyph?: 'globe' | 'plug' | 'terminal';
    /** The call completed by FAILING — the trace must be able to say so. */
    failed?: boolean;
    /** The arguments the agent actually passed — the "called with" half. */
    args: Record<string, unknown>;
    /** What the mock answered — labelled stand-in wherever it renders. */
    result: Record<string, unknown>;
}

export type RunEvent = ThoughtEvent | ToolEvent;

/** One staged situation arriving through a trigger, and the run it produces. */
export interface MockRun {
    slug: string;
    /** The backend scenario key, when this situation is live-runnable. */
    backendKey?: string;
    name: string;
    lead: {
        /** Subject (email) / channel (slack) / contact (whatsapp). */
        title: string;
        /** Generic one-line fallback for terse surfaces (timeline row). */
        meta: string;
        body: string;
        author?: string;
        /** Their address — an email or a phone number. */
        handle?: string;
        time?: string;
    };
    events: RunEvent[];
    doneAt: number;
    /** Builder-authored run (created via "+"): renamable, removable, and its
        WHOLE displayed lead rides to the backend as the patch — screen and
        run cannot diverge for content the registry never saw. */
    custom?: boolean;
    /** Null when the right behaviour was restraint — nothing goes out. A run
        may send SEVERAL things (a reply to the lead AND a briefing to the
        team), so this is a list. */
    /** provider is the sender's real slug (backend tool-name prefix) — it may
        be any wired node, not just a chat channel; the outcome frame routes by
        SHAPE (subject ⇒ envelope) and looks the mark up by this slug. */
    artifacts: {
        provider: string;
        to: string;
        text: string;
        subject?: string;
        /** A media payload riding the send (real runs: image/video/document
            sends). url renders a preview; kind alone renders a chip. */
        media?: { kind: 'image' | 'video' | 'audio' | 'file'; url?: string };
    }[] | null;
    /** Shown at done when there is no artifact: what it chose and why. */
    outcome?: string;
}

export interface TriggerFixture {
    slug: string;
    name: string;
    /** The node's display name, as the catalog would render it. */
    nodeName: string;
    triggerLabel: string;
    /** 'generic' for trigger types without native renderings — they get the
        document shape and the amber bolt instead of a provider icon. */
    provider: Provider | 'generic';
    /** Icon lookup key when the provider is 'generic' — the node's real slug,
        so an unmodelled trigger still wears its own logo. Semantics (raw-JSON
        scenario, no editing) stay keyed on provider. */
    iconSlug?: string;
    /** The node's selected trigger operation — the themed frames respond to
        it (a PR trigger renders a PR card, invoice.paid an invoice). */
    operation?: string;
    mocks: MockRun[];
}

/** What the variants consume: one trigger composed with one of its mocks. */
export type Scenario = Omit<TriggerFixture, 'mocks'> & MockRun & { key: string };

export function composeScenario(trigger: TriggerFixture, mockSlug: string): Scenario {
    const mock = trigger.mocks.find((m) => m.slug === mockSlug) ?? trigger.mocks[0];
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { mocks: _mocks, ...t } = trigger;
    return { ...t, ...mock, key: `${trigger.slug}:${mock.slug}` };
}

export const AGENT_NAME = 'Inbound Lead Response Agent';

const BRIEFING =
    'Casey Example at Example Manufacturing wants purchase-order requests ' +
    'from a shared inbox routed into Slack with approval links. Their operations ' +
    'team has about twelve people and is comparing options. We should confirm ' +
    'the workflow, share the relevant pricing, and offer a short walkthrough.';

export const TRIGGERS: TriggerFixture[] = [
    {
        slug: 'email',
        name: 'Email',
        nodeName: 'Gmail',
        triggerLabel: 'Staged email',
        provider: 'gmail',
        mocks: [
            {
                slug: 'qualified',
                name: 'Qualified lead',
                lead: {
                    title: 'Routing purchase-order approvals into Slack',
                    meta: 'Casey Example <casey@example-manufacturing.example>',
                    author: 'Casey Example',
                    handle: 'casey@example-manufacturing.example',
                    time: '09:32',
                    body:
                        "I'm Casey, Operations Manager at Example Manufacturing. My team reviews " +
                        'purchase-order requests in a shared inbox. I’d like new requests to land ' +
                        'in Slack with an approval link. Is that something you support, and roughly ' +
                        'what does it cost for a team of about twelve?',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 1000,
                        text: 'An inbound lead with a concrete use case. I should find the channel the team uses for leads before posting anything.',
                    },
                    {
                        kind: 'tool',
                        at: 1800,
                        completeAt: 3200,
                        step: 's1',
                        text: 'List channels in workspace',
                        provider: 'slack',
                        args: { types: 'public_channel', limit: 100 },
                        result: {
                            channels: [
                                { id: 'C0EXAMPLE1', name: 'inbound-leads' },
                                { id: 'C0EXAMPLE2', name: 'sales' },
                                { id: 'C0EXAMPLE3', name: 'general' },
                            ],
                        },
                    },
                    {
                        kind: 'thought',
                        at: 3700,
                        text: '#inbound-leads is where these go. Drafting a short briefing: who she is, what she wants, and the next step.',
                    },
                    {
                        kind: 'tool',
                        at: 4300,
                        completeAt: 5600,
                        step: 's2',
                        text: 'Send message to channel',
                        provider: 'slack',
                        args: { channel: '#inbound-leads', text: BRIEFING },
                        result: { ok: true, ts: '1700000000.000002', channel: 'C0EXAMPLE1' },
                    },
                ],
                doneAt: 6200,
                artifacts: [{ provider: 'slack', to: '#inbound-leads', text: BRIEFING }],
            },
            {
                slug: 'deep',
                name: 'Deep research',
                lead: {
                    title: 'Routing purchase-order approvals into Slack',
                    meta: 'Casey Example <casey@example-manufacturing.example>',
                    author: 'Casey Example',
                    handle: 'casey@example-manufacturing.example',
                    time: '09:32',
                    body:
                        "I'm Casey, Operations Manager at Example Manufacturing. My team reviews " +
                        'purchase-order requests in a shared inbox. I’d like new requests to land ' +
                        'in Slack with an approval link. Is that something you support, and roughly ' +
                        'what does it cost for a team of about twelve?',
                },
                // The breadth test: provider tools, providerless tools (web,
                // MCP), a FAILED call and its recovery, eight calls deep, and
                // two artifacts out. If the view holds here it holds anywhere.
                events: [
                    {
                        kind: 'thought',
                        at: 900,
                        text: 'A qualified lead — worth two minutes of homework before the team sees it.',
                    },
                    {
                        kind: 'tool',
                        at: 1600,
                        completeAt: 2800,
                        step: 's1',
                        text: 'Search the web',
                        glyph: 'globe',
                        args: { query: 'Example Manufacturing purchase-order workflow' },
                        result: {
                            results: [
                                {
                                    title: 'Example Manufacturing — Purchase-order workflow',
                                    url: 'https://news.example/example-manufacturing-workflow',
                                },
                                {
                                    title: 'Example Manufacturing — About',
                                    url: 'https://example-manufacturing.example/about',
                                },
                            ],
                        },
                    },
                    {
                        kind: 'tool',
                        at: 3300,
                        completeAt: 4400,
                        step: 's2',
                        text: 'Fetch a page',
                        glyph: 'globe',
                        args: { url: 'https://example-manufacturing.example/about' },
                        result: {
                            status: 200,
                            title: 'About — Example Manufacturing',
                            excerpt:
                                'Example Manufacturing is a fictional forty-person company used only for this rehearsal.',
                        },
                    },
                    {
                        kind: 'tool',
                        at: 4900,
                        completeAt: 5700,
                        step: 's3',
                        text: 'Look up contact in CRM',
                        glyph: 'plug',
                        args: { email: 'casey@example-manufacturing.example' },
                        result: {
                            found: true,
                            contact: {
                                name: 'Casey Example',
                                title: 'Head of Operations',
                                company: 'Example Manufacturing',
                                last_touch: null,
                            },
                        },
                    },
                    {
                        kind: 'thought',
                        at: 6100,
                        text: 'No prior CRM history. Checking the shared inbox for earlier threads all the same.',
                    },
                    {
                        kind: 'tool',
                        at: 6600,
                        completeAt: 7600,
                        step: 's4',
                        text: 'Fetch emails from inbox',
                        provider: 'gmail',
                        args: { query: 'from:example-manufacturing.example', max_results: 5, include_body: false },
                        result: { email_count: 0, emails: [] },
                    },
                    {
                        kind: 'tool',
                        at: 8100,
                        completeAt: 8800,
                        step: 's5',
                        text: 'Send message to channel',
                        provider: 'slack',
                        failed: true,
                        args: { channel: '#leads', text: 'New lead: Casey Example, Example Manufacturing…' },
                        result: { ok: false, error: 'channel_not_found' },
                    },
                    {
                        kind: 'thought',
                        at: 9200,
                        text: '#leads does not exist in this workspace — listing channels to find the right one.',
                    },
                    {
                        kind: 'tool',
                        at: 9700,
                        completeAt: 10500,
                        step: 's6',
                        text: 'List channels in workspace',
                        provider: 'slack',
                        args: { types: 'public_channel', limit: 100 },
                        result: {
                            channels: [
                                { id: 'C0EXAMPLE1', name: 'inbound-leads' },
                                { id: 'C0EXAMPLE2', name: 'sales' },
                            ],
                        },
                    },
                    {
                        kind: 'tool',
                        at: 11000,
                        completeAt: 11900,
                        step: 's7',
                        text: 'Send message to channel',
                        provider: 'slack',
                        args: { channel: '#inbound-leads', text: BRIEFING },
                        result: { ok: true, ts: '1700000000.000003', channel: 'C0EXAMPLE1' },
                    },
                    {
                        kind: 'tool',
                        at: 12400,
                        completeAt: 13400,
                        step: 's8',
                        text: 'Reply to the email',
                        provider: 'gmail',
                        args: {
                            body: 'Hi Casey — yes, we can route approval requests from a shared inbox into Slack. I’ll send pricing for twelve teammates today and can show you a short example workflow this week.',
                        },
                        result: { sent: true, message_id: 'example-reply-deep' },
                    },
                ],
                doneAt: 14000,
                artifacts: [
                    {
                        provider: 'slack',
                        to: '#inbound-leads',
                        text: BRIEFING,
                    },
                    {
                        provider: 'gmail',
                        to: 'casey@example-manufacturing.example',
                        subject: 'Re: Routing purchase-order approvals into Slack',
                        text: 'Hi Casey — yes, we can route approval requests from a shared inbox into Slack. I’ll send pricing for twelve teammates today and can show you a short example workflow this week.',
                    },
                ],
            },
            {
                slug: 'thin',
                name: 'Thin inquiry',
                lead: {
                    title: 'Quick question',
                    meta: 'Sam Example <sam@brightops.example>',
                    author: 'Sam Example',
                    handle: 'sam@brightops.example',
                    time: '11:05',
                    body: 'Hi — does your product work with Slack? Thanks, Sam',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 3000,
                        text: 'One line, no company context, no use case. A briefing would be empty — better to ask Sam for specifics and only brief the team when there is something to say.',
                    },
                    {
                        kind: 'tool',
                        at: 4600,
                        completeAt: 7200,
                        step: 's1',
                        text: 'Reply to the email',
                        provider: 'gmail',
                        args: {
                            body:
                                'Hi Sam — yes, Slack is where we live. So I can point you at the right ' +
                                'setup: what would you want landing in Slack, and roughly how big is the ' +
                                'team? Happy to send pricing once I know a bit more.',
                        },
                        result: { sent: true, message_id: 'example-reply-thin' },
                    },
                ],
                doneAt: 7800,
                artifacts: [{
                    provider: 'gmail',
                    to: 'sam@brightops.example',
                    subject: 'Re: Quick question',
                    text:
                        'Hi Sam — yes, Slack is where we live. So I can point you at the right ' +
                        'setup: what would you want landing in Slack, and roughly how big is the ' +
                        'team? Happy to send pricing once I know a bit more.',
                }],
            },
            {
                slug: 'newsletter',
                name: 'Newsletter',
                lead: {
                    title: '🚀 5 growth hacks your ops team needs this quarter',
                    meta: 'Example Bulletin <newsletter@bulletin.example>',
                    author: 'Example Bulletin',
                    handle: 'newsletter@bulletin.example',
                    time: '08:00',
                    body: 'Unlock the secrets top logistics teams use to 10x their pipeline! This week: cold outreach templates, the AI tools everyone is talking about, and more…',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 2600,
                        text: 'This is a marketing newsletter, not a lead. Posting it to #inbound-leads would be noise — the team would learn to ignore the channel.',
                    },
                ],
                doneAt: 4200,
                artifacts: null,
                outcome:
                    'It recognised a newsletter and left it alone — no briefing, nothing sent. Restraint is part of the job: a channel full of noise trains the team to stop reading it.',
            },
            {
                slug: 'complaint',
                name: 'Customer complaint',
                lead: {
                    title: 'Carrier feed has been down for two days',
                    meta: 'Taylor Example <taylor@example-freight.example>',
                    author: 'Taylor Example',
                    handle: 'taylor@example-freight.example',
                    time: '07:48',
                    body: 'Our fictional inventory sync stopped updating Tuesday night. Two days now. My team is back to checking records by hand, which is what we pay you to prevent. Who is looking at this?',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 2900,
                        text: 'This is an existing customer with an outage, not a lead. It cannot wait in the sales channel unmarked — flagging it with an explicit not-a-lead handoff.',
                    },
                    {
                        kind: 'tool',
                        at: 4400,
                        completeAt: 6900,
                        step: 's1',
                        text: 'Send message to channel',
                        provider: 'slack',
                        args: {
                            channel: '#inbound-leads',
                            text: '⚠️ Not a lead — existing customer issue. Taylor Example (Example Freight) reports their fictional inventory sync has been stale since Tuesday. Needs support/engineering attention, not sales.',
                        },
                        result: { ok: true, ts: '1700000000.000004', channel: 'C0EXAMPLE1' },
                    },
                ],
                doneAt: 7500,
                artifacts: [{
                    provider: 'slack',
                    to: '#inbound-leads',
                    text: '⚠️ Not a lead — existing customer issue. Taylor Example (Example Freight) reports their fictional inventory sync has been stale since Tuesday. Needs support/engineering attention, not sales.',
                }],
            },
            {
                slug: 'vendor',
                name: 'Vendor pitch',
                lead: {
                    title: 'Partnership opportunity — API data enrichment',
                    meta: 'Riley Example <riley@example-data.example>',
                    author: 'Riley Example',
                    handle: 'riley@example-data.example',
                    time: '10:22',
                    body: 'Hi team — Riley from Example Data here. We provide firmographic enrichment APIs and I think there’s a great fit with what you’re building. Would love to get 30 minutes on your calendar this week to explore a partnership.',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 2700,
                        text: 'Someone selling to us, not buying from us. Not a lead, not urgent, and not worth a briefing — the team can find it in the inbox if they ever want it.',
                    },
                ],
                doneAt: 4300,
                artifacts: null,
                outcome:
                    'It recognised a vendor pitch and left it in the inbox — no briefing, no reply, nothing sent. The leads channel stays for leads.',
            },
        ],
    },
    {
        slug: 'slack',
        name: 'Slack',
        nodeName: 'Slack',
        triggerLabel: 'Staged message · Slack',
        provider: 'slack',
        mocks: [
            {
                slug: 'mention',
                name: 'Teammate asks',
                lead: {
                    title: '#inbound-leads',
                    meta: 'Jordan Example · 09:14',
                    author: 'Jordan Example',
                    time: '09:14',
                    body: '@lead-agent anyone looked at the Example Manufacturing note yet? Casey pinged again this morning about the approval workflow.',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 2800,
                        text: 'Jordan is asking for status on an existing lead. I should pull the original thread before answering.',
                    },
                    {
                        kind: 'tool',
                        at: 4400,
                        completeAt: 9100,
                        step: 's1',
                        text: 'Fetch emails from inbox',
                        provider: 'gmail',
                        args: { query: 'from:casey@example-manufacturing.example', max_results: 5, include_body: false },
                        result: {
                            email_count: 2,
                            emails: [
                                {
                                    from: 'Casey Example <casey@example-manufacturing.example>',
                                    subject: 'Routing purchase-order approvals into Slack',
                                    date: 'Mon, 01 Jan 2024',
                                },
                                {
                                    from: 'Casey Example <casey@example-manufacturing.example>',
                                    subject: 'Re: Routing purchase-order approvals into Slack',
                                    date: 'Tue, 02 Jan 2024',
                                },
                            ],
                        },
                    },
                    {
                        kind: 'thought',
                        at: 9500,
                        text: 'Two emails, the second unanswered since this morning. Summarising the state and handing Jordan the next step.',
                    },
                    {
                        kind: 'tool',
                        at: 9900,
                        completeAt: 12100,
                        step: 's2',
                        text: 'Send message to channel',
                        provider: 'slack',
                        args: {
                            channel: '#inbound-leads',
                            thread_ts: '1700000000.000005',
                            text: 'Status on Example Manufacturing: Casey sent an initial note and followed up this morning — still unanswered. She wants purchase-order approvals routed into Slack for about twelve people. Someone should reply today.',
                        },
                        result: { ok: true, ts: '1700000000.000006', channel: 'C0EXAMPLE1' },
                    },
                ],
                doneAt: 12700,
                artifacts: [{
                    provider: 'slack',
                    to: '#inbound-leads (thread)',
                    text: 'Status on Example Manufacturing: Casey sent an initial note and followed up this morning — still unanswered. She wants purchase-order approvals routed into Slack for about twelve people. Someone should reply today.',
                }],
            },
        ],
    },
    {
        slug: 'whatsapp',
        name: 'WhatsApp',
        nodeName: 'WhatsApp',
        triggerLabel: 'Staged message · WhatsApp',
        provider: 'whatsapp',
        mocks: [
            {
                slug: 'lead',
                name: 'Direct lead',
                lead: {
                    title: 'Casey Example',
                    meta: '+1 (415) 555-0184 · 09:41',
                    author: 'Casey Example',
                    handle: '+1 (415) 555-0184',
                    time: '09:41',
                    body: 'Hi — found you through an ops group. Can you route purchase-order approvals from email into Slack? Team of about 12. What does it cost?',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 3000,
                        text: 'A direct question from a lead on WhatsApp. Answer her there first, then brief the team so someone owns the follow-up.',
                    },
                    {
                        kind: 'tool',
                        at: 4800,
                        completeAt: 7600,
                        step: 's1',
                        text: 'Send text message',
                        provider: 'whatsapp',
                        args: {
                            to: '+12025550107',
                            text: 'Hi Casey — yes, we can route approval requests from email into Slack. For twelve teammates I’ll send the relevant pricing and a short example workflow today. Any required approval fields?',
                        },
                        result: { sent: true, message_id: 'wamid.synthetic-reply-001' },
                    },
                    {
                        kind: 'tool',
                        at: 8100,
                        completeAt: 10400,
                        step: 's2',
                        text: 'Send message to channel',
                        provider: 'slack',
                        args: {
                            channel: '#inbound-leads',
                            text: 'WhatsApp lead: Casey Example (Example Manufacturing) asked about email approval requests → Slack for twelve teammates. I confirmed the workflow and promised pricing plus an example today — needs an owner.',
                        },
                        result: { ok: true, ts: '1700000000.000007', channel: 'C0EXAMPLE1' },
                    },
                ],
                doneAt: 11000,
                artifacts: [{
                    provider: 'whatsapp',
                    to: 'Casey · WhatsApp',
                    text: 'Hi Casey — yes, we can route approval requests from email into Slack. For twelve teammates I’ll send the relevant pricing and a short example workflow today. Any required approval fields?',
                },
                {
                    provider: 'slack',
                    to: '#inbound-leads',
                    text: 'WhatsApp lead: Casey Example (Example Manufacturing) asked about email approval requests → Slack for twelve teammates. I confirmed the workflow and promised pricing plus an example today — needs an owner.',
                }],
            },
            {
                slug: 'optout',
                name: 'Opt-out',
                lead: {
                    title: 'Morgan Example',
                    meta: '+1 (415) 555-0139 · 08:57',
                    author: 'Morgan Example',
                    handle: '+1 (415) 555-0139',
                    time: '08:57',
                    body: 'Please stop messaging me. Not interested.',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 2400,
                        text: 'A clear opt-out. No reply, no pitch — the worst possible move here is another message.',
                    },
                ],
                doneAt: 3800,
                artifacts: null,
                outcome:
                    'It read a clear opt-out and stayed silent — no reply, no pitch, nothing sent.',
            },
        ],
    },
];
