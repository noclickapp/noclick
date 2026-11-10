import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TwoChatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/2chat.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TwoChatNode: NodeDefinition = {
    type: 'automation-2chat', label: '2Chat',
    category: 'communication',
    description: 'Automate WhatsApp messages, contacts, tags, SMS and account reads',
    Icon: TwoChatIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TwoChatIcon} iconColor="" />),
};
