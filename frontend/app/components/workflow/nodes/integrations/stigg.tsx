// Stigg customer, catalog and entitlement node for native workflows.
// Uses the official inline brand SVG preserved from Stigg's website.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.stigg.io/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/stigg-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const StiggNode: NodeDefinition = {
    type: 'automation-stigg',
    label: 'Stigg',
    category: 'developer-tools',
    description: 'Customer metadata, product catalogs, paywalls and entitlement checks',
    keywords: ['Stigg', 'entitlements', 'paywall', 'customer', 'plans', 'add-ons', 'SaaS'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 56 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
