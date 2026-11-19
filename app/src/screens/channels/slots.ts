// The channels layer's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise.
import type { ComponentType } from 'react';
import { slot } from '@/slots';
import type { AvatarSize } from './avatars';
import { InitialsFace } from './slotStandards';
import type { AgentChoice, AgentState, ChannelMember } from './types';

export interface AgentFaceProps {
    member: ChannelMember;
    /** Its job in a line, as the account keeps it or the member says it; empty when nothing says. */
    role: string;
    /** The size it's drawn at, in pixels. */
    size: AvatarSize;
    state?: AgentState;
    /** `false`: none of its state's marks on it, where a ring round it already says the state. */
    marks?: boolean;
    /** Its box: its size, and whatever the place it's drawn in adds. */
    className: string;
}

/** An agent's face, wherever a channel draws one (members, messages, pickers, who's at work). The standard is its
 *  initials on its own colour. */
export const AGENT_FACE = slot<ComponentType<AgentFaceProps>>('channels.agent.face', InitialsFace);

export type MoreAgentChoice = Extract<AgentChoice, { source: 'automation' }>;

export interface MoreAgents {
    /** Their heading in the pickers. */
    label: string;
    /** The agents it offers. */
    list(): Promise<MoreAgentChoice[]>;
    /** Puts one of them in a channel; throws an Error whose message is the sentence to show. */
    add(channelId: string, agent: MoreAgentChoice): Promise<void>;
}

/** In the pickers that put an agent in a channel (a new channel's, a channel's members, `/invite`): a group of agents
 *  from somewhere other than the platform, and putting one in. Nothing stands there: the pickers offer the platform's
 *  agents alone. */
export const MORE_AGENTS = slot<MoreAgents | null>('channels.picker.moreAgents', null);
