import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://www.assemblyai.com

// Sourced brand artwork: https://logos.composio.dev/api/assemblyai
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/assemblyai-preferred-brand.svg" dark="/icons/assemblyai-preferred-brand-dark.svg" className={className} style={style} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AssemblyAINodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" width={DIMENSIONS.width}
        height={DIMENSIONS.height} iconSize={DIMENSIONS.iconSize} />
);

export const AssemblyAINode: NodeDefinition = {
    type: 'automation-assemblyai',
    label: 'AssemblyAI',
    description: 'Transcribe, search, and export audio with AssemblyAI',
    category: 'ai',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AssemblyAINodeComponent),
};
