import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Vector brand artwork from https://www.act.com/uploads/Act-Partner-Branding-Kit-0223.pdf
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/act-crm-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ActCRMNode: NodeDefinition = {
    type: 'automation-act-crm',
    label: 'Act CRM',
    description: 'Act! Web API contacts, companies, groups, opportunities, activity metadata and linked notes',
    category: 'crm-sales',
    keywords: ['Act', 'CRM', 'contacts', 'companies', 'opportunities', 'notes'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
