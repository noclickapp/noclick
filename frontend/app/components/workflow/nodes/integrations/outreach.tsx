import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.outreach.ai/home
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/outreach-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OutreachNode: NodeDefinition = {
    type: 'automation-outreach',
    label: 'Outreach',
    category: 'crm-sales',
    description: 'Prospects, accounts, sequences, tasks, calls, and opportunities',
    Icon: OfficialBrandIcon,
    iconColor: 'text-blue-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="text-blue-500" />
    )),
};
