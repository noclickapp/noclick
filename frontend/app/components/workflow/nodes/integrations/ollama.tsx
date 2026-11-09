import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OllamaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ollama.png" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const OllamaNode: NodeDefinition = {
    type: 'automation-ollama', category: 'ai', label: 'Ollama',
    description: 'Generate text and embeddings, manage models, and read cloud usage',
    Icon: OllamaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OllamaIcon} iconColor="" />),
};
