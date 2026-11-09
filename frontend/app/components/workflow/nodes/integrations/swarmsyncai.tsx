import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SwarmsyncaiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/swarmsyncai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SwarmsyncaiNode: NodeDefinition = {
    type: 'automation-swarmsyncai', category: 'ai', label: 'Swarmsyncai',
    description: 'Discover agents, manage needs and work orders, exchange messages, and track SwarmSync transactions',
    Icon: SwarmsyncaiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SwarmsyncaiIcon} iconColor="" />),
};
