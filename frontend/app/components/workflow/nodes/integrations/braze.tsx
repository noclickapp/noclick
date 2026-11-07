import type { CSSProperties as BrandCSSProperties } from 'react';
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Sourced brand artwork: https://logos.composio.dev/api/braze
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/braze-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const BrazeNode: NodeDefinition = {
    type: 'automation-braze',
    label: 'Braze',
    description: 'Manage customer engagement, campaigns, Canvases, users, catalogs, and analytics',
    Icon: PreferredBrandIcon,
    iconColor: 'text-orange-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="text-orange-500" />
    )),
};
