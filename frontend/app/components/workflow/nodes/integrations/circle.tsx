import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CircleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/circle.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CircleNode: NodeDefinition = {
    type: 'automation-circle', category: 'courses', label: 'Circle',
    description: 'Manage community members, spaces, posts, comments and member tags',
    keywords: ['community', 'membership', 'circle.so'],
    Icon: CircleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CircleIcon} iconColor="" />),
};
