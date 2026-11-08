import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZigpollIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zigpoll.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ZigpollNode: NodeDefinition = {
    type: 'automation-zigpoll', label: 'Zigpoll',
    category: 'forms',
    description: 'Create surveys, collect feedback, send invitations and analyze responses',
    Icon: ZigpollIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZigpollIcon} iconColor="" />),
};
