import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FeltIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/felt.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FeltNode: NodeDefinition = {
    type: 'automation-felt', category: 'analytics-bi', label: 'Felt',
    description: 'Create and manage maps, projects, layers and annotations',
    Icon: FeltIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FeltIcon} iconColor="" />),
};
