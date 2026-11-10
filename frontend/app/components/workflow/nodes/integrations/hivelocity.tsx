import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://hivelocity.net

// Sourced brand artwork: https://www.hivelocity.net/
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/hivelocity-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const HivelocityNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />
);
export const HivelocityNode: NodeDefinition = {
    type: 'automation-hivelocity', category: 'cloud-hosting', label: 'Hivelocity',
    description: 'Protected device status, type, provisioning flags and monitor count metadata',
    Icon: PreferredBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(HivelocityNodeComponent),
};
