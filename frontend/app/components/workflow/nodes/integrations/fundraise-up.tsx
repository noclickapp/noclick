// Native Fundraise Up metadata and designation workflow node.
// The complete official API-documentation wordmark is retained without tracing or cropping.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://fundraiseup.com/identity-guidelines/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/fundraise-up-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FundraiseUpNode: NodeDefinition = {
    type: 'automation-fundraise-up', category: 'nonprofit', label: 'Fundraise Up',
    description: 'Read fundraising metadata and manage designations',
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
