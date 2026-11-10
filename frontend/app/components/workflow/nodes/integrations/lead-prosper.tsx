import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeadProsperIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lead-prosper.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LeadProsperNode: NodeDefinition = {
    type: 'automation-lead-prosper', category: 'crm-sales', label: 'Lead Prosper',
    description: 'Monitor new leads, manage campaigns and clients, control traffic and caps, and return leads',
    keywords: ['lead distribution', 'lead routing', 'buyers', 'suppliers'],
    Icon: LeadProsperIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeadProsperIcon} iconColor="" />),
};
