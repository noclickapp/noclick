// ThoughtSpot native analytics node for tenant-bound v2 API workflows.
// Uses the vendor's original mark and the shared automation component, so
// credentials and operation forms follow the current canvas implementation.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://www.thoughtspot.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/thoughtspot-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ThoughtSpotNode: NodeDefinition = {
    type: 'automation-thoughtspot',
    label: 'ThoughtSpot',
    description: 'Liveboards, saved Answers, bounded analytics data and reports',
    category: 'analytics-bi',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
