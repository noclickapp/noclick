import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OllamaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/ollama.svg" dark="/icons/ollama-dark.svg" className={className} style={style} />
);

export const OllamaNode: NodeDefinition = {
    type: 'automation-ollama', category: 'ai', label: 'Ollama',
    description: 'Watch for new or updated models, generate text and embeddings, and manage Ollama models',
    Icon: OllamaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OllamaIcon} iconColor="" />),
};
