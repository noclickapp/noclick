// Formbricks registers its catalog and canvas definition through this module.
// The canvas component and sourced provider artwork load when this integration is used.
import type { CSSProperties as BrandCSSProperties } from 'react';
import { memo } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Sourced brand artwork: https://formbricks.com/_next/static/media/footerlogo.e272c0f1.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/formbricks-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FormbricksNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />
);

export const FormbricksNode: NodeDefinition = {
    type: 'automation-formbricks',
    label: 'Formbricks',
    description: 'Manage surveys, responses, contacts, actions, and webhooks',
    category: 'forms',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FormbricksNodeComponent),
};
