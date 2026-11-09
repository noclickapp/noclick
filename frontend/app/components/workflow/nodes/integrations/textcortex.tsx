import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TextcortexIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/textcortex.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TextcortexNode: NodeDefinition = {
    type: 'automation-textcortex', category: 'ai', label: 'TextCortex',
    description: 'Generate text and images, search the web and query your knowledge bases',
    keywords: ['textcortex', 'AI', 'chat', 'knowledge base', 'document retrieval'],
    Icon: TextcortexIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TextcortexIcon} iconColor="" />),
};
