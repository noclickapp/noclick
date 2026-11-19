// The emoji a work chat reaches for, by the names Slack gives them, so
// `:tada:` and the picker agree. Curated rather than complete: the picker
// stays one short scroll, and the search still finds each by its words.

export interface Emoji {
    char: string;
    name: string;
    /** Other words it answers to in search. */
    words?: string;
}

export const EMOJI_SECTIONS: { title: string; items: Emoji[] }[] = [
    {
        title: 'Frequently used',
        items: [
            { char: '👍', name: 'thumbsup', words: '+1 yes like agree' },
            { char: '✅', name: 'white_check_mark', words: 'done check yes' },
            { char: '👀', name: 'eyes', words: 'looking watching' },
            { char: '🙏', name: 'pray', words: 'thanks please' },
            { char: '🎉', name: 'tada', words: 'party celebrate' },
            { char: '🔥', name: 'fire', words: 'hot lit' },
            { char: '❤️', name: 'heart', words: 'love' },
            { char: '😂', name: 'joy', words: 'laugh lol' },
            { char: '🙌', name: 'raised_hands', words: 'hooray yay' },
            { char: '💯', name: '100', words: 'perfect' },
            { char: '🚀', name: 'rocket', words: 'ship launch' },
            { char: '👏', name: 'clap', words: 'applause' },
        ],
    },
    {
        title: 'Smileys',
        items: [
            { char: '😀', name: 'grinning', words: 'happy' },
            { char: '😄', name: 'smile', words: 'happy' },
            { char: '😅', name: 'sweat_smile', words: 'phew' },
            { char: '😊', name: 'blush', words: 'happy' },
            { char: '😉', name: 'wink' },
            { char: '😍', name: 'heart_eyes', words: 'love' },
            { char: '🤩', name: 'star_struck', words: 'wow' },
            { char: '😎', name: 'sunglasses', words: 'cool' },
            { char: '🤔', name: 'thinking', words: 'hmm' },
            { char: '🙃', name: 'upside_down_face', words: 'silly' },
            { char: '😐', name: 'neutral_face', words: 'meh' },
            { char: '😬', name: 'grimacing', words: 'yikes awkward' },
            { char: '😮', name: 'open_mouth', words: 'wow surprised' },
            { char: '🤯', name: 'exploding_head', words: 'mind blown' },
            { char: '🥳', name: 'partying_face', words: 'party' },
            { char: '😴', name: 'sleeping', words: 'tired' },
            { char: '😢', name: 'cry', words: 'sad' },
            { char: '😭', name: 'sob', words: 'sad' },
            { char: '😤', name: 'triumph', words: 'determined' },
            { char: '🫡', name: 'saluting_face', words: 'on it yes sir' },
        ],
    },
    {
        title: 'Hands and people',
        items: [
            { char: '👋', name: 'wave', words: 'hello hi bye' },
            { char: '👌', name: 'ok_hand', words: 'ok perfect' },
            { char: '✌️', name: 'v', words: 'peace' },
            { char: '🤞', name: 'crossed_fingers', words: 'luck hope' },
            { char: '💪', name: 'muscle', words: 'strong' },
            { char: '👉', name: 'point_right' },
            { char: '👆', name: 'point_up' },
            { char: '🤝', name: 'handshake', words: 'deal' },
            { char: '🫶', name: 'heart_hands', words: 'love thanks' },
            { char: '🤖', name: 'robot', words: 'agent bot' },
            { char: '🧠', name: 'brain', words: 'smart' },
            { char: '👩‍💻', name: 'technologist', words: 'coder developer' },
        ],
    },
    {
        title: 'Work',
        items: [
            { char: '📌', name: 'pushpin', words: 'pin' },
            { char: '📎', name: 'paperclip', words: 'attach' },
            { char: '📅', name: 'date', words: 'calendar' },
            { char: '⏰', name: 'alarm_clock', words: 'time reminder' },
            { char: '📈', name: 'chart_with_upwards_trend', words: 'growth up' },
            { char: '📉', name: 'chart_with_downwards_trend', words: 'down' },
            { char: '💡', name: 'bulb', words: 'idea' },
            { char: '📝', name: 'memo', words: 'note write' },
            { char: '📣', name: 'mega', words: 'announce' },
            { char: '✉️', name: 'email', words: 'mail letter' },
            { char: '📞', name: 'telephone_receiver', words: 'phone call' },
            { char: '💬', name: 'speech_balloon', words: 'chat comment' },
            { char: '🐛', name: 'bug', words: 'issue' },
            { char: '⚡', name: 'zap', words: 'fast lightning' },
            { char: '🛠️', name: 'hammer_and_wrench', words: 'tools fix' },
            { char: '🔒', name: 'lock', words: 'secure private' },
            { char: '🔑', name: 'key', words: 'secret' },
            { char: '📦', name: 'package', words: 'ship deploy' },
            { char: '💸', name: 'money_with_wings', words: 'spend cost' },
            { char: '☕', name: 'coffee', words: 'break' },
        ],
    },
    {
        title: 'Symbols',
        items: [
            { char: '⚠️', name: 'warning', words: 'careful' },
            { char: '❌', name: 'x', words: 'no wrong' },
            { char: '❓', name: 'question' },
            { char: '❗', name: 'exclamation', words: 'important' },
            { char: '⭐', name: 'star', words: 'favorite' },
            { char: '✨', name: 'sparkles', words: 'new magic' },
            { char: '🎯', name: 'dart', words: 'goal target' },
            { char: '🏁', name: 'checkered_flag', words: 'finish' },
            { char: '🟢', name: 'large_green_circle', words: 'green go' },
            { char: '🔴', name: 'red_circle', words: 'red stop' },
        ],
    },
];

const ALL = EMOJI_SECTIONS.flatMap((section) => section.items);

/** Emoji whose name starts with the query first, then any whose name or words contain it. */
export function searchEmoji(query: string): Emoji[] {
    const q = query.trim().toLowerCase().replace(/^:|:$/g, '');
    if (!q) return ALL;
    const starts = ALL.filter((e) => e.name.startsWith(q));
    const contains = ALL.filter((e) => !e.name.startsWith(q) && (e.name.includes(q) || e.words?.split(' ').some((w) => w.startsWith(q))));
    return [...starts, ...contains];
}
