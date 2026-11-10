// Arcads AI UGC video / AI-actor ad generation automation node definition.
// Provides workflow integration with the Arcads external REST API (products,
// folders, scripts, AI-actor video/image/talking-actor generation, Veo 3.1 / Omnihuman, and asset polling).

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://www.arcads.ai
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/arcads-brand-vector.svg" dark="/icons/arcads-brand-vector-dark.svg" className={className} style={style} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ArcadsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
};

export const ArcadsNode: NodeDefinition = {
    type: 'automation-arcads',
    label: 'Arcads',
    description: 'Arcads AI UGC video generation',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ArcadsNodeComponent),
};
