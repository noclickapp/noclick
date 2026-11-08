import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CompanyenrichIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/companyenrich.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CompanyenrichNode: NodeDefinition = {
    type: 'automation-companyenrich', category: 'crm-sales', label: 'CompanyEnrich',
    description: 'Enrich companies and people, search prospects, and manage saved company lists',
    keywords: ['enrichment', 'prospecting', 'leads', 'company data'],
    Icon: CompanyenrichIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CompanyenrichIcon} iconColor="" />),
};
