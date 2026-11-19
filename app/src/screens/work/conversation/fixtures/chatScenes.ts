// A WhatsApp agent's chats as the fake /v1 serves them, for the tests and a local preview of how Work draws a turn a
// chat app's message started (ChatTurn): each conversation's history (the trigger's message and the turn's reply) and
// its activity items (agents.activity's wire shape: what came in, what the agent did, the turn). A contact it answers
// twice (a photo, then a question it replies to and notes), a busy group it stays quiet in, a voice note it reacts to
// and sets a reminder from, a call held for the owner's yes, the owner's own chat, and a turn still at work.
type Json = Record<string, unknown>;

export const WHATSAPP = 'automation-whatsapp';
export const TRIGGER_ID = 'trg-whatsapp';
export const CONNECTION = 'whatsapp';

const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
/** A time `days` ahead at `hour`:00, as wake_me's `at` names one. */
const ahead = (days: number, hour: number) => {
    const d = new Date();
    d.setDate(d.getDate() + days);
    d.setHours(hour, 0, 0, 0);
    return d.toISOString();
};

interface Turn {
    id: string;
    minutesAgo: number;
    worked: number;
    sender: { name: string | null; id: string; number?: string | null; avatar?: string | null };
    text?: string;
    media?: Json;
    quoted?: string;
    did: Json[];
    status?: 'running' | 'done' | 'failed';
    steps?: string[];
    /** What the agent said last (a quiet turn's reason). */
    said?: string;
    /** Messages that came in after the first while it was busy, answered by the same turn (its `also_inbound`). */
    more?: { sender: Turn['sender']; text: string; secondsLater: number }[];
}

const did = (kind: string, fields: Json = {}): Json => ({ kind, text: null, emoji: null, at: null, held_request_id: null, message_id: null, tool: null, ...fields });

/** One conversation: the chat it is, and its turns oldest first. */
function scene(chat: Json, turns: Turn[]): { conversation: string; history: Json[]; activity: Json[] } {
    const history: Json[] = [];
    const activity: Json[] = [];
    for (const t of turns) {
        const started = at(t.minutesAgo);
        history.push({ id: `${t.id}-in`, role: 'user', text: `[WhatsApp] ${t.sender.name ?? 'Someone'}: ${t.text ?? ''}`, created_at: started, operation_id: t.id, trigger: { kind: 'event', id: TRIGGER_ID, title: t.sender.name ?? 'Someone' } });
        if (t.status !== 'running') history.push({ id: `${t.id}-out`, role: 'assistant', text: t.said ?? 'Done.', created_at: at(t.minutesAgo - t.worked / 60), operation_id: t.id });
        const message = (sender: Turn['sender'], fields: Json, n: number): Json => ({ sender_name: sender.name, sender_id: sender.id, sender_number: sender.number ?? null, sender_avatar: sender.avatar ?? null, text: '', media: null, quoted_text: null, message_id: `${t.id}-msg${n ? `-${n}` : ''}`, ...fields });
        const first = message(t.sender, { text: t.text ?? '', media: t.media ?? null, quoted_text: t.quoted ?? null, at: started }, 0);
        activity.unshift({
            chat,
            inbound: first,
            also_inbound: (t.more ?? []).map((m, i) => message(m.sender, { text: m.text, at: new Date(Date.parse(started) + m.secondsLater * 1000).toISOString() }, i + 1)),
            did: t.did.map((d, i) => ({ ...d, at: d.at ?? at(t.minutesAgo - (Math.max(0, ...(t.more ?? []).map((m) => m.secondsLater)) + i + 1) / 60) })),
            turn: {
                id: t.id,
                conversation_id: `ck:wf:agent:sdk:account:agent:${chat.key}`,
                status: t.status ?? 'done',
                started_at: started,
                worked_s: t.status === 'running' ? null : t.worked,
                started_by: { kind: 'event', id: TRIGGER_ID, title: t.sender.name },
                steps: (t.steps ?? []).map((tool) => ({ tool, at: started, error: null })),
            },
        });
    }
    return { conversation: String(chat.key), history, activity };
}

const PRIYA = '12025550101@c.us';
const TREK = '120000000000000001@g.us';
const MOM = '12025550103@c.us';
const RAHUL = '12025550104@c.us';
const OWN = '12025550100@c.us';

const chat = (key: string, fields: Json): Json => ({ key, name: null, kind: 'direct', number: null, avatar: null, node_type: WHATSAPP, ...fields });

export const CHAT_SCENES = {
    contact: () =>
        scene(chat(PRIYA, { name: 'Priya Shah', number: '+12025550101' }), [
            {
                id: 'op-priya-1',
                minutesAgo: 95,
                worked: 3,
                sender: { name: 'Priya Shah', id: PRIYA, number: '+12025550101' },
                text: 'The menu for the tasting',
                media: { kind: 'image', url: null, duration: null, transcript: null },
                did: [did('reaction', { emoji: '🙏', tool: 'whatsapp__send_reaction_emoji', message_id: 'op-priya-1-msg' }), did('reply', { text: 'Thanks Priya, I’ve passed it to Rowan.', tool: 'whatsapp__send_text_message' })],
                steps: ['whatsapp__send_reaction_emoji', 'whatsapp__send_text_message'],
            },
            {
                id: 'op-priya-2',
                minutesAgo: 12,
                worked: 4,
                sender: { name: 'Priya Shah', id: PRIYA, number: '+12025550101' },
                text: 'Hey! Are you around Thursday evening for the tasting?',
                did: [did('reply', { text: 'Hi Priya, Rowan’s free after 6 on Thursday. Want me to hold 6:30 for the tasting?', tool: 'whatsapp__send_text_message' }), did('note', { text: 'Priya: tasting on Thursday, offered 6:30', tool: 'memory__note' })],
                steps: ['whatsapp__send_text_message', 'memory__note'],
            },
        ]),
    group: () =>
        scene(chat(TREK, { name: 'Weekend trek', kind: 'group' }), [
            {
                id: 'op-trek-1',
                minutesAgo: 8,
                worked: 2,
                sender: { name: 'Arjun', id: '12025550105@c.us', number: '+12025550105' },
                text: 'Who’s bringing the stove? Tents are sorted.',
                said: 'A question to the whole group, and nobody asked for Rowan.',
                did: [did('quiet', { text: 'A question to the whole group, and nobody asked for Rowan.' })],
            },
        ]),
    voice: () =>
        scene(chat(MOM, { name: 'Mom', number: '+12025550103' }), [
            {
                id: 'op-mom-1',
                minutesAgo: 6,
                worked: 5,
                sender: { name: 'Mom', id: MOM, number: '+12025550103' },
                media: { kind: 'voice', url: null, duration: 42, transcript: 'Beta, are you coming for dinner on Sunday? Bring the good mangoes from the market.' },
                did: [
                    did('reaction', { emoji: '❤️', tool: 'whatsapp__send_reaction_emoji', message_id: 'op-mom-1-msg' }),
                    did('reply', { text: 'Hi! Rowan’s coming on Sunday. I’ll remind him about the mangoes.', tool: 'whatsapp__send_text_message' }),
                    did('reminder', { text: 'buy mangoes', when: ahead(2, 11), tool: 'wake_me' }),
                ],
                steps: ['whatsapp__send_reaction_emoji', 'whatsapp__send_text_message', 'wake_me'],
            },
        ]),
    held: () =>
        scene(chat(RAHUL, { name: 'Rahul Mehta', number: '+12025550104' }), [
            {
                id: 'op-rahul-1',
                minutesAgo: 4,
                worked: 6,
                sender: { name: 'Rahul Mehta', id: RAHUL, number: '+12025550104' },
                text: 'Can you email me last month’s invoice?',
                quoted: 'Sending the October numbers today',
                did: [
                    did('found', { text: 'October invoice', tool: 'web__search' }),
                    did('held', { text: 'send email: the October invoice to Rahul', tool: 'gmail__send_email', held_request_id: 'req-held' }),
                    did('reply', { text: 'I’ve found it. It goes out as soon as Rowan okays it.', tool: 'whatsapp__send_text_message' }),
                ],
                steps: ['web__search', 'gmail__send_email', 'whatsapp__send_text_message'],
            },
        ]),
    self: () =>
        scene(chat(OWN, { name: 'Rowan', kind: 'self', number: '+12025550100' }), [
            {
                id: 'op-own-1',
                minutesAgo: 3,
                worked: 3,
                sender: { name: 'Rowan', id: OWN, number: '+12025550100' },
                text: 'Remind me to call the bank at 5',
                did: [did('reminder', { text: 'call the bank', when: 'in 45 minutes', tool: 'wake_me' }), did('reply', { text: 'Done, I’ll remind you at 5.', tool: 'whatsapp__send_text_message' })],
                steps: ['wake_me', 'whatsapp__send_text_message'],
            },
        ]),
    /** Three messages that came in while it was busy, answered in one turn. */
    burst: () =>
        scene(chat(TREK, { name: 'Weekend trek', kind: 'group' }), [
            {
                id: 'op-trek-burst',
                minutesAgo: 5,
                worked: 4,
                sender: { name: 'Arjun', id: '12025550105@c.us', number: '+12025550105' },
                text: 'Rowan are you driving Saturday?',
                more: [
                    { sender: { name: 'Arjun', id: '12025550105@c.us', number: '+12025550105' }, text: 'We need one more car', secondsLater: 60 },
                    { sender: { name: 'Sana', id: '12025550106@c.us', number: '+12025550106' }, text: 'I can take two people', secondsLater: 150 },
                ],
                did: [
                    did('reaction', { emoji: '👍', tool: 'whatsapp__send_reaction_emoji', message_id: 'op-trek-burst-msg-1' }),
                    did('reply', { text: 'Rowan’s driving on Saturday, with room for three.', tool: 'whatsapp__send_text_message' }),
                ],
                steps: ['whatsapp__send_reaction_emoji', 'whatsapp__send_text_message'],
            },
        ]),
    /** A turn still at work: what came in, nothing done yet. */
    running: () =>
        scene(chat(PRIYA, { name: 'Priya Shah', number: '+12025550101' }), [
            { id: 'op-live', minutesAgo: 0.1, worked: 0, status: 'running', sender: { name: 'Priya Shah', id: PRIYA, number: '+12025550101' }, text: 'Could you also book a table for four after?', did: [] },
        ]),
};

export type ChatSceneName = keyof typeof CHAT_SCENES;

/** The held call's approval, as GET /v1/humans/requests/{id} reads it while it waits. */
export const HELD_REQUEST: Json = { object: 'human_request', id: 'req-held', kind: 'approve', status: 'pending', message: 'WhatsApp wants to run gmail.send_email. Approve it?', options: null, answer: null, expires_at: null, owner_can_answer: true };

/** The agent's WhatsApp trigger, which names the connection its chats' pictures are kept on. */
export const WHATSAPP_TRIGGER: Json = { object: 'trigger', id: TRIGGER_ID, kind: 'event', spec: { connection: CONNECTION, event: 'message' }, status: 'active', state: 'live' };
