import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CrewAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/crew-ai.svg" dark="/icons/crew-ai-dark.svg" className={className} style={style} />
);

export const CrewAINode: NodeDefinition = {
    type: 'automation-crew-ai', category: 'ai', label: 'CrewAI',
    description: 'Discover deployment inputs, start crews, check results and resume human feedback tasks',
    keywords: ['crew ai', 'crew_ai', 'agents', 'AMP'],
    Icon: CrewAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CrewAIIcon} iconColor="" />),
};
