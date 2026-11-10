// Native Skyvia workspace and management metadata node.
// Uses the current shared editor shell and exact official vendor SVG.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://skyvia.com

// Sourced brand artwork: https://skyvia.com/assets/img/sprite.svg#logo
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/skyvia-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SkyviaNode: NodeDefinition = {
    type: 'automation-skyvia', category: 'analytics-bi', label: 'Skyvia',
    description: 'Read workspace, connection, integration, backup and automation metadata',
    Icon: PreferredBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />),
};
