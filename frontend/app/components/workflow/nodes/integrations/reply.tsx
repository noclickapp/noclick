import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ReplyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/reply.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ReplyNode: NodeDefinition = {
    type: 'automation-reply', label: 'Reply',
    description: 'Manage contacts, contact lists, sequences and tasks',
    keywords: ['reply.io', 'sales engagement', 'outreach', 'prospects'],
    Icon: ReplyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReplyIcon} iconColor="" />),
};
