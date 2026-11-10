import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NotraIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/notra.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const NotraNode: NodeDefinition = {
    type: 'automation-notra', category: 'marketing', label: 'Notra',
    description: 'Create content, generate posts, schedule publishing and manage brand identities',
    Icon: NotraIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NotraIcon} iconColor="" />),
};
