import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoogleAIStudioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/google-ai-studio.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GoogleAIStudioNode: NodeDefinition = {
    type: 'automation-google-ai-studio', category: 'ai', label: 'Google AI Studio (Gemini)',
    description: 'Generate content, embed text, manage files, context caches and file search',
    keywords: ['Gemini', 'Google AI', 'LLM', 'embeddings'],
    Icon: GoogleAIStudioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoogleAIStudioIcon} iconColor="" />),
};
