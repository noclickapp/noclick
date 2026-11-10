import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LinqIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/linq.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LinqNode: NodeDefinition = {
    type: 'automation-linq', label: 'Linq',
    category: 'communication',
    description: 'Send messages and manage Linq iMessage conversations, reactions and blocked handles',
    Icon: LinqIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LinqIcon} iconColor="" />),
};
