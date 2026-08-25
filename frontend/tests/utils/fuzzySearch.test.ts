import { describe, expect, it } from 'vitest';
import { fuzzyFilter, matchTerm, scoreFields, type SearchField } from '~/utils/fuzzySearch';

// Models how OperationPicker builds fields for a single action: label is the
// strongest signal, then identity keywords (the raw operation value/title),
// category, and a low-weight description for synonym recall.
function fields(opts: {
    label: string;
    keywords?: string;
    category?: string;
    trigger?: boolean;
    description?: string;
}): SearchField[] {
    const f: SearchField[] = [{ text: opts.label.toLowerCase(), weight: 1, fuzzy: true }];
    if (opts.keywords) f.push({ text: opts.keywords.toLowerCase(), weight: 0.6, fuzzy: true });
    if (opts.category) f.push({ text: opts.category.toLowerCase(), weight: 0.4 });
    if (opts.trigger) f.push({ text: 'trigger', weight: 0.3 });
    if (opts.description) f.push({ text: opts.description.toLowerCase(), weight: 0.25 });
    return f;
}

const sendMessage = fields({
    label: 'Send Message',
    keywords: 'send message',
    category: 'Message',
});
const deleteMessage = fields({
    label: 'Delete Message',
    keywords: 'delete message',
    category: 'Message',
    description: 'Remove a message from a channel',
});
const listChannels = fields({ label: 'List Channels', keywords: 'list channels', category: 'Channel' });
const newMessageTrigger = fields({
    label: 'New Message',
    keywords: 'on new message',
    category: 'Message',
    trigger: true,
});

function rank(options: { name: string; fields: SearchField[] }[], query: string) {
    return options
        .map((o) => ({ name: o.name, score: scoreFields(o.fields, query) }))
        .filter((o) => o.score !== null)
        .sort((a, b) => (b.score as number) - (a.score as number))
        .map((o) => o.name);
}

describe('matchTerm tiering', () => {
    it('ranks exact > prefix > word-boundary > mid-word substring', () => {
        const exact = matchTerm('send', 'send', false)!;
        const prefix = matchTerm('send message', 'send', false)!;
        const boundary = matchTerm('send message', 'message', false)!;
        const midword = matchTerm('username', 'name', false)!;
        expect(exact).toBeGreaterThan(prefix);
        expect(prefix).toBeGreaterThan(boundary);
        expect(boundary).toBeGreaterThan(midword);
    });

    it('only falls back to subsequence when fuzzy is enabled', () => {
        expect(matchTerm('send message', 'snmsg', false)).toBeNull();
        expect(matchTerm('send message', 'snmsg', true)).not.toBeNull();
    });

    it('rejects characters scattered too far apart', () => {
        expect(matchTerm('send a message to a channel later', 'sl', true)).toBeNull();
    });
});

describe('scoreFields semantics', () => {
    it('is word-order independent', () => {
        expect(scoreFields(sendMessage, 'message send')).not.toBeNull();
        expect(scoreFields(sendMessage, 'send message')).not.toBeNull();
    });

    it('requires every token to match (AND)', () => {
        // "send" matches but "carrier" matches nothing on Send Message.
        expect(scoreFields(sendMessage, 'send carrier')).toBeNull();
    });

    it('matches abbreviations via fuzzy subsequence on identity fields', () => {
        expect(scoreFields(sendMessage, 'msg')).not.toBeNull();
        expect(scoreFields(sendMessage, 'sndmsg')).not.toBeNull();
    });

    it('matches synonyms that only live in the description', () => {
        // "remove" is nowhere in the label/value but is in Delete Message's prose.
        expect(scoreFields(deleteMessage, 'remove')).not.toBeNull();
        expect(scoreFields(sendMessage, 'remove')).toBeNull();
    });

    it('matches on category', () => {
        expect(scoreFields(listChannels, 'channel')).not.toBeNull();
    });
});

describe('ranking across options', () => {
    const all = [
        { name: 'Send Message', fields: sendMessage },
        { name: 'Delete Message', fields: deleteMessage },
        { name: 'List Channels', fields: listChannels },
        { name: 'New Message', fields: newMessageTrigger },
    ];

    it('puts the exact-label match first', () => {
        expect(rank(all, 'send message')[0]).toBe('Send Message');
    });

    it('an abbreviation surfaces the intended action ahead of weaker matches', () => {
        const ranked = rank(all, 'send msg');
        expect(ranked[0]).toBe('Send Message');
    });

    it('a trigger is reachable by the word "trigger"', () => {
        expect(rank(all, 'trigger')).toContain('New Message');
    });
});

describe('fuzzyFilter (list search)', () => {
    // Models the agent trigger-selection modal's GitHub trigger rows — the
    // regression that motivated the shared helper.
    interface Trig {
        displayName: string;
        operation: string;
        description: string;
    }
    const githubTriggers: Trig[] = [
        {
            displayName: 'On Pull Request Opened',
            operation: 'on_pull_request_opened',
            description: 'Trigger: fires when a pull request is opened.',
        },
        {
            displayName: 'On Pull Request Closed',
            operation: 'on_pull_request_closed',
            description: 'Trigger: fires when a pull request is closed without being merged.',
        },
        {
            displayName: 'On Issue Comment',
            operation: 'on_issue_comment',
            description: 'Trigger: fires when a comment is made on an issue or pull request.',
        },
    ];
    const trigFields = (t: Trig): SearchField[] => [
        { text: t.displayName.toLowerCase(), weight: 1, fuzzy: true },
        { text: t.operation.toLowerCase(), weight: 0.6, fuzzy: true },
        { text: t.description.toLowerCase(), weight: 0.4 },
    ];

    it('matches multi-word reordered queries the old substring filter missed', () => {
        // The exact reported case: "pull opened" never matched via .includes().
        const res = fuzzyFilter(githubTriggers, 'pull opened', trigFields);
        expect(res.map((t) => t.displayName)).toEqual(['On Pull Request Opened']);
    });

    it('returns the full list unchanged for an empty/blank query', () => {
        expect(fuzzyFilter(githubTriggers, '', trigFields)).toEqual(githubTriggers);
        expect(fuzzyFilter(githubTriggers, '   ', trigFields)).toEqual(githubTriggers);
    });

    it('drops items that fail any token', () => {
        expect(fuzzyFilter(githubTriggers, 'issue comment', trigFields).map((t) => t.displayName)).toEqual([
            'On Issue Comment',
        ]);
    });
});
