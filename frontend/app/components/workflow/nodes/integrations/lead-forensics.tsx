import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeadForensicsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lead-forensics.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LeadForensicsNode: NodeDefinition = {
    type: 'automation-lead-forensics', category: 'crm-sales', label: 'Lead Forensics',
    description: 'Read identified businesses, website visits, pages, lead KPIs and account reference data',
    Icon: LeadForensicsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeadForensicsIcon} iconColor="" />),
};
