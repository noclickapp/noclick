// Voiceflow canvas definition. Discovered alongside its generated metadata.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://www.voiceflow.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/voiceflow-brand-vector.svg" dark="/icons/voiceflow-brand-vector-dark.svg" className={className} style={style} />
);

export const VoiceflowNode: NodeDefinition = {
    type: 'automation-voiceflow',
    label: 'Voiceflow',
    description: 'Project, environment and knowledge base metadata',
    category: 'ai',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
