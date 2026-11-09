import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SalesRabbitIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/salesrabbit.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SalesRabbitNode: NodeDefinition = {
    type: 'automation-salesrabbit', category: 'crm-sales', label: 'SalesRabbit',
    description: 'Manage leads, appointments, contacts and notes in SalesRabbit',
    Icon: SalesRabbitIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SalesRabbitIcon} iconColor="" />),
};
