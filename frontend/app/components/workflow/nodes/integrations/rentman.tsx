// Registers Rentman in the workflow catalog and canvas. The provider mark identifies
// the account operations whose forms come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RentmanIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rentman.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const RentmanNode: NodeDefinition = {
    type: 'automation-rentman', label: 'Rentman',
    description: 'Manage rental contacts, projects, equipment, crew, tasks and invoices',
    keywords: ['rental', 'event production', 'equipment planning'],
    Icon: RentmanIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RentmanIcon} iconColor="" />),
};
