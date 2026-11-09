import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WriterIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/writer.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const WriterNode: NodeDefinition = {
    type: 'automation-writer', category: 'ai', label: 'Writer',
    description: 'Generate text, query Knowledge Graphs, manage files and run applications',
    keywords: ['Palmyra', 'AI Studio', 'knowledge graph'],
    Icon: WriterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WriterIcon} iconColor="" />),
};
