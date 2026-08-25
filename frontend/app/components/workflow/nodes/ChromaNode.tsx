// Chroma vector database node definition.
// Provides workflow integration for similarity search, add/get/delete records,
// and collection management via the Chroma v2 REST API. Part of the external
// vector-database node set.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

const ChromaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/chroma.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
ChromaIcon.displayName = 'ChromaIcon';

const ChromaNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ChromaIcon} iconColor="" iconSize={56} />;
};

export const ChromaNode: NodeDefinition = {
    type: 'automation-chroma',
    label: 'Chroma',
    description: 'Vector database',
    keywords: ['RAG', 'vector search', 'vector database', 'vector db', 'retrieval', 'embeddings', 'semantic search', 'similarity search', 'knowledge base', 'nearest neighbor'],
    Icon: ChromaIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ChromaNodeComponent),
};
