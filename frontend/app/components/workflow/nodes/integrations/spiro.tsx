import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SpiroIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/spiro.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SpiroNode: NodeDefinition = {
    type: 'automation-spiro', category: 'crm-sales', label: 'Spiro',
    description: 'Manage contacts, companies, opportunities, activities, notes and reminders',
    Icon: SpiroIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SpiroIcon} iconColor="" />),
};
