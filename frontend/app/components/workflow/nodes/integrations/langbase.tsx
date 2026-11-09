import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LangbaseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/langbase.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LangbaseNode: NodeDefinition = {
    type: 'automation-langbase', category: 'ai', label: 'Langbase',
    description: 'Run AI pipes, search memory and manage conversation threads',
    keywords: ['AI', 'agents', 'RAG', 'embeddings', 'memory', 'LLM'],
    Icon: LangbaseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LangbaseIcon} iconColor="" />),
};
