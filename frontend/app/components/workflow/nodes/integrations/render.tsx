// Render cloud infrastructure automation node.
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://render.com
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/render-brand.svg" dark="/icons/render-brand-dark.svg" className={className} style={style} />
);

const RenderNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const RenderNode: NodeDefinition = {
    type: 'automation-render',
    label: 'Render',
    description: 'Manage services, deploys, databases, and infrastructure',
    category: 'cloud-hosting',
    keywords: [
        'render',
        'cloud',
        'deploy',
        'hosting',
        'service',
        'database',
        'postgres',
        'infrastructure',
    ],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: RenderNodeComponent,
};
