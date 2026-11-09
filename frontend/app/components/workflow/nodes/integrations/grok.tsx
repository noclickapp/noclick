import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GrokIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/grok.svg" dark="/icons/grok-dark.svg" className={className} style={style} />
);

export const GrokNode: NodeDefinition = {
    type: 'automation-grok', category: 'ai', label: 'Grok', keywords: ['xAI'],
    description: 'Generate text, embeddings, images and videos with xAI, manage stored responses and files, and trigger on new team files',
    Icon: GrokIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GrokIcon} iconColor="" />),
};
