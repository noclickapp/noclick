// LassoCRM exposes project-scoped real estate CRM operations on the workflow canvas.
// The official provider mark identifies its manually connected API key account.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LassoCRMIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lassocrm.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain', background: '#244c66', padding: 3, borderRadius: 4 } as CSSProperties} />
);

export const LassoCRMNode: NodeDefinition = {
    type: 'automation-lassocrm', category: 'crm-sales', label: 'LassoCRM',
    description: 'Manage registrants, contact details, notes, activities, appointments and inventory',
    keywords: ['Lasso', 'real estate', 'homebuilder', 'leads'],
    Icon: LassoCRMIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LassoCRMIcon} iconColor="" />),
};
