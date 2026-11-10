// Discover Synthflow AI in the canvas and integration catalog.
// The publisher's mark identifies its call and contact automation tools.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SynthflowAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/synthflow-ai.svg" className={className} style={style} />
);

export const SynthflowAiNode: NodeDefinition = {
    type: 'automation-synthflow-ai', category: 'ai', label: 'Synthflow AI',
    description: 'Make calls and manage agents, contacts, knowledge bases, actions and phone numbers',
    keywords: ['synthflow', 'voice', 'outbound calls', 'AI calling'],
    Icon: SynthflowAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SynthflowAiIcon} iconColor="" />),
};
