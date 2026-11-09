import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DealMachineIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dealmachine.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DealMachineNode: NodeDefinition = {
    type: 'automation-dealmachine', category: 'crm-sales', label: 'DealMachine',
    description: 'Search properties and manage prospects, notes, lists, tasks and tags',
    keywords: ['real estate', 'property', 'lead', 'prospect'],
    Icon: DealMachineIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DealMachineIcon} iconColor="" />),
};
