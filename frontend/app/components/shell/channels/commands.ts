// A channel's slash commands: what each one does and takes, and the pure
// parts of running one (reading the message, finding who it names, catching
// up on a channel). The page applies what they decide: most change the
// channel through the API; /summarize answers you alone, and /remind and
// /automate hand the ask to NoClick, which keeps reminders and builds
// automations.
import { Archive, AlarmClock, CornerDownRight, MessagesSquare, PenLine, ScrollText, UserMinus, UserPlus, Workflow, type LucideIcon } from 'lucide-react';
import { authorMember } from './model';
import type { ChannelMember, ChannelMessage } from './types';

export interface ChannelCommand {
    name: 'summarize' | 'handoff' | 'invite' | 'remove' | 'topic' | 'mode' | 'close' | 'remind' | 'automate';
    description: string;
    /** What follows the command, shown as its hint. */
    args?: string;
    icon: LucideIcon;
}

export const CHANNEL_COMMANDS: ChannelCommand[] = [
    { name: 'summarize', description: 'Catch up on this channel', icon: ScrollText },
    { name: 'handoff', description: 'Hand the work to an agent', args: '@agent what to do', icon: CornerDownRight },
    { name: 'invite', description: 'Add one of your agents', args: '@agent', icon: UserPlus },
    { name: 'remove', description: 'Take a member out', args: '@name', icon: UserMinus },
    { name: 'topic', description: 'Change the channel topic', args: 'new topic', icon: PenLine },
    { name: 'mode', description: 'Agents answer @-mentions, or every message', args: 'mentions | all', icon: MessagesSquare },
    { name: 'close', description: 'Close the channel', icon: Archive },
    { name: 'remind', description: 'Ask NoClick to remind you', args: 'me to … in 2h', icon: AlarmClock },
    { name: 'automate', description: 'Ask NoClick to turn this into an automation', args: 'what should happen', icon: Workflow },
];

/** A message that starts with `/word`: the command it names (if any) and what follows. */
export function parseCommand(text: string): { name: string; command?: ChannelCommand; args: string } | null {
    const match = /^\/([a-z]+)(?:\s+([\s\S]*))?$/i.exec(text.trim());
    if (!match) return null;
    const name = match[1].toLowerCase();
    return { name, command: CHANNEL_COMMANDS.find((c) => c.name === name), args: (match[2] ?? '').trim() };
}

/** The first of `members` named in `text` (`@Scout` or just `Scout`), and the words around it. */
export function mentionedMember<M extends { name: string }>(text: string, members: M[]): { member: M; rest: string } | null {
    for (const member of [...members].sort((a, b) => b.name.length - a.name.length)) {
        const pattern = new RegExp(`(?:^|\\s)@?${member.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w-])`, 'i');
        if (pattern.test(text)) return { member, rest: text.replace(pattern, ' ').replace(/\s+/g, ' ').trim() };
    }
    return null;
}

function firstSentence(markdown: string): string {
    const plain = markdown
        .replace(/```[\s\S]*?```/g, '')
        .replace(/[*_~`>]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    const sentence = /^.*?[.!?](?=\s|$)/.exec(plain)?.[0] ?? plain;
    return sentence.length > 120 ? `${sentence.slice(0, 117).trimEnd()}…` : sentence;
}

/** Who said what lately, as a short markdown list. */
export function summarizeChannel(name: string, messages: ChannelMessage[], members: ChannelMember[]): string {
    const spoken = messages.filter((m) => !m.ephemeral && !m.pending && (m.text.trim() || m.attachments.length)).slice(-6);
    if (!spoken.length) return `Nothing to catch up on in #${name} yet.`;
    const lines = spoken.map((m) => {
        const who = m.author.type === 'system' ? 'NoClick' : (authorMember(m.author, members)?.name ?? m.author.name);
        const said = m.text.trim() ? firstSentence(m.text) : `shared ${m.attachments.map((a) => a.name).join(', ')}`;
        return `- **${who}**: ${said}`;
    });
    return [`Here's where #${name} stands:`, ...lines].join('\n');
}
