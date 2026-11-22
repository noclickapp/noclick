/* Canned rehearsal runs for iterating on the testing UX without paying a real
   ~15s agent run per look. Structure mirrors how rehearsal data really shapes:
   a TRIGGER carries several staged situations (mocks), because "new email" is
   not one situation — a qualified lead, a one-line inquiry and a newsletter
   should produce visibly different agent behaviour, including the behaviour of
   doing nothing at all.

   The qualified-lead timings and briefing are captured from an actual run of
   the sales agent (2026-08-09); the rest is hand-authored to the same rhythm.
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

/** A media payload riding a message, in or out. `url` renders a real preview
    (image/video/audio player); kind alone renders a chip. `name` is the
    filename an inbound attachment arrived with. */
export interface MediaRef {
    kind: 'image' | 'video' | 'audio' | 'file';
    url?: string;
    name?: string;
    /** What the agent's media digest read from it — a voice note's
        transcript, carried on the persisted record so the frame shows what
        was said under the player. */
    transcript?: string;
}

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
        /** What they attached — a voice note, photo, document. Real runs
            only; a message can be media alone, with an empty body. */
        media?: MediaRef;
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
            sends). */
        media?: MediaRef;
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
    'New lead from Priya Raman, Head of Ops at Northwind Logistics. They are ' +
    'looking for a solution to push carrier status updates into Slack ' +
    'automatically. They’re interested in whether we support this and the cost ' +
    'for a team of about twenty. Next steps: respond to Priya with our ' +
    'capabilities and pricing options.';

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
                    title: 'Pushing carrier status into Slack — possible?',
                    meta: 'Priya Raman <priya@northwind.io>',
                    author: 'Priya Raman',
                    handle: 'priya@northwind.io',
                    time: '09:32',
                    body:
                        "I'm Priya, Head of Ops at Northwind Logistics. We move a lot of freight " +
                        'and my team currently checks carrier portals by hand several times a day. ' +
                        "I'd like status updates to land in Slack automatically instead. Is that " +
                        'something you support, and roughly what does it cost for a team of about twenty?',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 3200,
                        text: 'An inbound lead with a concrete use case. I should find the channel the team uses for leads before posting anything.',
                    },
                    {
                        kind: 'tool',
                        at: 5000,
                        completeAt: 10200,
                        step: 's1',
                        text: 'List channels in workspace',
                        provider: 'slack',
                        args: { types: 'public_channel', limit: 100 },
                        result: {
                            channels: [
                                { id: 'C0A1B2C3D', name: 'inbound-leads' },
                                { id: 'C0A1B2C3E', name: 'sales' },
                                { id: 'C0A1B2C3F', name: 'general' },
                            ],
                        },
                    },
                    {
                        kind: 'thought',
                        at: 10600,
                        text: '#inbound-leads is where these go. Drafting a short briefing: who she is, what she wants, and the next step.',
                    },
                    {
                        kind: 'tool',
                        at: 11000,
                        completeAt: 13200,
                        step: 's2',
                        text: 'Send message to channel',
                        provider: 'slack',
                        args: { channel: '#inbound-leads', text: BRIEFING },
                        result: { ok: true, ts: '1786.2201', channel: 'C0A1B2C3D' },
                    },
                ],
                doneAt: 13800,
                artifacts: [{ provider: 'slack', to: '#inbound-leads', text: BRIEFING }],
            },
            {
                slug: 'deep',
                name: 'Deep research',
                lead: {
                    title: 'Pushing carrier status into Slack — possible?',
                    meta: 'Priya Raman <priya@northwind.io>',
                    author: 'Priya Raman',
                    handle: 'priya@northwind.io',
                    time: '09:32',
                    body:
                        "I'm Priya, Head of Ops at Northwind Logistics. We move a lot of freight " +
                        'and my team currently checks carrier portals by hand several times a day. ' +
                        "I'd like status updates to land in Slack automatically instead. Is that " +
                        'something you support, and roughly what does it cost for a team of about twenty?',
                },
                // The breadth test: provider tools, providerless tools (web,
                // MCP), a FAILED call and its recovery, eight calls deep, and
                // two artifacts out. If the view holds here it holds anywhere.
                events: [
                    {
                        kind: 'thought',
                        at: 2600,
                        text: 'A qualified lead — worth two minutes of homework before the team sees it.',
                    },
                    {
                        kind: 'tool',
                        at: 4200,
                        completeAt: 7600,
                        step: 's1',
                        text: 'Search the web',
                        glyph: 'globe',
                        args: { query: 'Northwind Logistics freight visibility funding' },
                        result: {
                            results: [
                                {
                                    title: 'Northwind Logistics raises $12M Series A',
                                    url: 'https://techledger.io/northwind-series-a',
                                },
                                {
                                    title: 'Northwind Logistics — About',
                                    url: 'https://northwindlogistics.com/about',
                                },
                            ],
                        },
                    },
                    {
                        kind: 'tool',
                        at: 8000,
                        completeAt: 11400,
                        step: 's2',
                        text: 'Fetch a page',
                        glyph: 'globe',
                        args: { url: 'https://northwindlogistics.com/about' },
                        result: {
                            status: 200,
                            title: 'About — Northwind Logistics',
                            excerpt:
                                'Northwind gives freight teams real-time visibility across 40+ carriers. 80 people, Chicago and Rotterdam.',
                        },
                    },
                    {
                        kind: 'tool',
                        at: 11800,
                        completeAt: 14100,
                        step: 's3',
                        text: 'Look up contact in CRM',
                        glyph: 'plug',
                        args: { email: 'priya@northwind.io' },
                        result: {
                            found: true,
                            contact: {
                                name: 'Priya Raman',
                                title: 'Head of Operations',
                                company: 'Northwind Logistics',
                                last_touch: null,
                            },
                        },
                    },
                    {
                        kind: 'thought',
                        at: 14500,
                        text: 'No prior CRM history. Checking the shared inbox for earlier threads all the same.',
                    },
                    {
                        kind: 'tool',
                        at: 15000,
                        completeAt: 18200,
                        step: 's4',
                        text: 'Fetch emails from inbox',
                        provider: 'gmail',
                        args: { query: 'from:northwind.io', max_results: 5, include_body: false },
                        result: { email_count: 0, emails: [] },
                    },
                    {
                        kind: 'tool',
                        at: 18600,
                        completeAt: 20100,
                        step: 's5',
                        text: 'Send message to channel',
                        provider: 'slack',
                        failed: true,
                        args: { channel: '#leads', text: 'New lead: Priya Raman, Northwind Logistics…' },
                        result: { ok: false, error: 'channel_not_found' },
                    },
                    {
                        kind: 'thought',
                        at: 20500,
                        text: '#leads does not exist in this workspace — listing channels to find the right one.',
                    },
                    {
                        kind: 'tool',
                        at: 20900,
                        completeAt: 23000,
                        step: 's6',
                        text: 'List channels in workspace',
                        provider: 'slack',
                        args: { types: 'public_channel', limit: 100 },
                        result: {
                            channels: [
                                { id: 'C0A1B2C3D', name: 'inbound-leads' },
                                { id: 'C0A1B2C3E', name: 'sales' },
                            ],
                        },
                    },
                    {
                        kind: 'tool',
                        at: 23400,
                        completeAt: 25600,
                        step: 's7',
                        text: 'Send message to channel',
                        provider: 'slack',
                        args: { channel: '#inbound-leads', text: BRIEFING },
                        result: { ok: true, ts: '1786.2419', channel: 'C0A1B2C3D' },
                    },
                    {
                        kind: 'tool',
                        at: 26000,
                        completeAt: 28400,
                        step: 's8',
                        text: 'Reply to the email',
                        provider: 'gmail',
                        args: {
                            body: 'Hi Priya — yes, this is exactly what we do. Congrats on the Series A, by the way. Sending pricing for ~20 seats today, and happy to show you a live setup this week if useful.',
                        },
                        result: { sent: true, message_id: '19fdc5b02f13c8da' },
                    },
                ],
                doneAt: 29000,
                artifacts: [
                    {
                        provider: 'slack',
                        to: '#inbound-leads',
                        text: BRIEFING,
                    },
                    {
                        provider: 'gmail',
                        to: 'priya@northwind.io',
                        subject: 'Re: Pushing carrier status into Slack — possible?',
                        text: 'Hi Priya — yes, this is exactly what we do. Congrats on the Series A, by the way. Sending pricing for ~20 seats today, and happy to show you a live setup this week if useful.',
                    },
                ],
            },
            {
                slug: 'thin',
                name: 'Thin inquiry',
                lead: {
                    title: 'Quick question',
                    meta: 'Sam Vithanage <sam@getbrightops.com>',
                    author: 'Sam Vithanage',
                    handle: 'sam@getbrightops.com',
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
                        result: { sent: true, message_id: '19fdc4a11e02b7c9' },
                    },
                ],
                doneAt: 7800,
                artifacts: [{
                    provider: 'gmail',
                    to: 'sam@getbrightops.com',
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
                    meta: 'GrowthBlast <newsletter@growthblast.io>',
                    author: 'GrowthBlast',
                    handle: 'newsletter@growthblast.io',
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
                    meta: 'Elena Torres <elena@vantagefreight.com>',
                    author: 'Elena Torres',
                    handle: 'elena@vantagefreight.com',
                    time: '07:48',
                    body: 'Our carrier status feed stopped updating Tuesday night. Two days now. My team is back to checking portals by hand, which is what we pay you to prevent. Who is looking at this?',
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
                            text: '⚠️ Not a lead — existing customer outage. Elena Torres (Vantage Freight) reports their carrier feed dead since Tuesday and is understandably angry. Needs support/eng eyes now, not sales.',
                        },
                        result: { ok: true, ts: '1786.2412', channel: 'C0A1B2C3D' },
                    },
                ],
                doneAt: 7500,
                artifacts: [{
                    provider: 'slack',
                    to: '#inbound-leads',
                    text: '⚠️ Not a lead — existing customer outage. Elena Torres (Vantage Freight) reports their carrier feed dead since Tuesday and is understandably angry. Needs support/eng eyes now, not sales.',
                }],
            },
            {
                slug: 'vendor',
                name: 'Vendor pitch',
                lead: {
                    title: 'Partnership opportunity — API data enrichment',
                    meta: 'Colin Marsh <colin@dataspring.co>',
                    author: 'Colin Marsh',
                    handle: 'colin@dataspring.co',
                    time: '10:22',
                    body: 'Hi team — Colin from DataSpring here. We provide firmographic enrichment APIs and I think there’s a great fit with what you’re building. Would love to get 30 minutes on your calendar this week to explore a partnership.',
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
                    meta: 'Dana Okafor · 09:14',
                    author: 'Dana Okafor',
                    time: '09:14',
                    body: '@lead-agent anyone looked at the Northwind note yet? Priya pinged again this morning asking about the Slack integration.',
                },
                events: [
                    {
                        kind: 'thought',
                        at: 2800,
                        text: 'Dana is asking for status on an existing lead. I should pull the original thread before answering.',
                    },
                    {
                        kind: 'tool',
                        at: 4400,
                        completeAt: 9100,
                        step: 's1',
                        text: 'Fetch emails from inbox',
                        provider: 'gmail',
                        args: { query: 'from:priya@northwind.io', max_results: 5, include_body: false },
                        result: {
                            email_count: 2,
                            emails: [
                                {
                                    from: 'Priya Raman <priya@northwind.io>',
                                    subject: 'Pushing carrier status into Slack — possible?',
                                    date: 'Thu, 07 Aug 2026',
                                },
                                {
                                    from: 'Priya Raman <priya@northwind.io>',
                                    subject: 'Re: Pushing carrier status into Slack',
                                    date: 'Sat, 09 Aug 2026',
                                },
                            ],
                        },
                    },
                    {
                        kind: 'thought',
                        at: 9500,
                        text: 'Two emails, the second unanswered since this morning. Summarising the state and handing Dana the next step.',
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
                            thread_ts: '1786.1104',
                            text: 'Status on Northwind: Priya emailed Thursday and followed up this morning — still unanswered. She wants carrier status in Slack for ~20 people. Someone should reply today; her second email is the one to answer.',
                        },
                        result: { ok: true, ts: '1786.2288', channel: 'C0A1B2C3D' },
                    },
                ],
                doneAt: 12700,
                artifacts: [{
                    provider: 'slack',
                    to: '#inbound-leads (thread)',
                    text: 'Status on Northwind: Priya emailed Thursday and followed up this morning — still unanswered. She wants carrier status in Slack for ~20 people. Someone should reply today; her second email is the one to answer.',
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
                    title: 'Priya Raman',
                    meta: '+1 (415) 555-0184 · 09:41',
                    author: 'Priya Raman',
                    handle: '+1 (415) 555-0184',
                    time: '09:41',
                    body: 'Hi — found you through the Northwind ops group. Do you support pushing carrier status updates into Slack? Team of about 20. What does it cost?',
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
                            to: '+14155550184',
                            text: 'Hi Priya — yes, carrier status into Slack is exactly what we do. For a team of 20 you’d be on the Team plan; I’ll have someone send over pricing and a short demo today. Anything specific you’d want the updates to include?',
                        },
                        result: { sent: true, message_id: 'wamid.HBgLMTQxNTU1NTAxODQ' },
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
                            text: 'WhatsApp lead: Priya Raman (Northwind Logistics) asked about carrier status → Slack for ~20 seats. I confirmed we support it and promised pricing + a demo today — needs an owner.',
                        },
                        result: { ok: true, ts: '1786.2310', channel: 'C0A1B2C3D' },
                    },
                ],
                doneAt: 11000,
                artifacts: [{
                    provider: 'whatsapp',
                    to: 'Priya · WhatsApp',
                    text: 'Hi Priya — yes, carrier status into Slack is exactly what we do. For a team of 20 you’d be on the Team plan; I’ll have someone send over pricing and a short demo today. Anything specific you’d want the updates to include?',
                },
                {
                    provider: 'slack',
                    to: '#inbound-leads',
                    text: 'WhatsApp lead: Priya Raman (Northwind Logistics) asked about carrier status → Slack for ~20 seats. I confirmed we support it and promised pricing + a demo today — needs an owner.',
                }],
            },
            {
                slug: 'optout',
                name: 'Opt-out',
                lead: {
                    title: 'Marcus Bell',
                    meta: '+1 (415) 555-0139 · 08:57',
                    author: 'Marcus Bell',
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
