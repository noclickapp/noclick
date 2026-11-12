import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TalkrouteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/talkroute.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const TalkrouteNode: NodeDefinition = {
    type: 'automation-talkroute', category: 'communication', label: 'Talkroute',
    description: 'Send texts, manage contacts, read calls and voicemail, and receive new message, call and voicemail events',
    keywords: ['phone', 'SMS', 'text message', 'voicemail', 'call history'],
    Icon: TalkrouteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TalkrouteIcon} iconColor="" />),
};
