// LeadSimple exposes CRM and property-management operations through its REST API.
// This definition makes its generated schema available in the palette and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeadSimpleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/leadsimple.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const LeadSimpleNode: NodeDefinition = {
    type: 'automation-leadsimple', category: 'crm-sales', label: 'LeadSimple',
    description: 'Manage contacts, deals, processes, properties and notes',
    keywords: ['CRM', 'property management', 'sales pipeline'],
    Icon: LeadSimpleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeadSimpleIcon} iconColor="" />),
};
