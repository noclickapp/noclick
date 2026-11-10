// Buildkite's visual workflow node uses the official mark from the shared icon asset.
// This registers the provider's canvas presentation alongside its generated config schema.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://buildkite.com/about/brand-assets/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/buildkite-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const BuildkiteNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const BuildkiteNode: NodeDefinition = {
    type: 'automation-buildkite',
    label: 'Buildkite',
    description: 'Run pipelines and inspect CI builds',
    category: 'developer-tools',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(BuildkiteNodeComponent),
};
