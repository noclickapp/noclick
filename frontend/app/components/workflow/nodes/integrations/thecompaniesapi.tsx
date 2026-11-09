// Adds The Companies API to the workflow canvas and integration catalog.
// Its schema and credential metadata are generated from the self-registering node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ThecompaniesapiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/thecompaniesapi.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ThecompaniesapiNode: NodeDefinition = {
    type: 'automation-thecompaniesapi', category: 'crm-sales', label: 'The Companies API',
    description: 'Enrich and search companies, research prospects and manage company lists',
    keywords: ['thecompaniesapi', 'company enrichment', 'prospecting', 'lead generation'],
    Icon: ThecompaniesapiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ThecompaniesapiIcon} iconColor="" />),
};
