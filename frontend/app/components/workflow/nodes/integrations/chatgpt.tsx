// Defines the ChatGPT (OpenAI) node in the integration catalog and canvas.
// The backend schema owns its API operations and credential form.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ChatGPTIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/chatgpt.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ChatGPTNode: NodeDefinition = {
    type: 'automation-chatgpt', category: 'ai', label: 'ChatGPT (OpenAI)',
    description: 'Generate responses and embeddings, moderate text, and manage chats, files, batches and vector stores',
    keywords: ['chatgpt', 'openai', 'gpt', 'artificial intelligence', 'language model'],
    Icon: ChatGPTIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ChatGPTIcon} iconColor="" />),
};
