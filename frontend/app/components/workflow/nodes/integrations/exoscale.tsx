// Native Exoscale APIv2 metadata node for the workflow canvas.
// The original official icon is rendered unchanged; forms use the native generated schema.
import React, { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.exoscale.com/press/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/exoscale-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const ExoscaleNode: NodeDefinition = {
  type: 'automation-exoscale', category: 'cloud-hosting', label: 'Exoscale',
  description: 'Read signed APIv2 zone-local instance, capacity and anti-affinity metadata',
  keywords: ['Exoscale', 'cloud', 'compute', 'instance', 'capacity', 'anti-affinity', 'metadata'],
  Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(Component),
};
