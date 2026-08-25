// Weaviate vector database node definition.
// Provides workflow integration for vector/semantic search (GraphQL nearVector /
// nearText), object insert/get/delete, and schema management via the Weaviate
// REST + GraphQL APIs. Part of the external vector-database node set.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

const WeaviateIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/weaviate.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
WeaviateIcon.displayName = 'WeaviateIcon';

const WeaviateNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={WeaviateIcon} iconColor="" iconSize={56} />;
};

export const WeaviateNode: NodeDefinition = {
    type: 'automation-weaviate',
    label: 'Weaviate',
    description: 'Vector database',
    keywords: ['RAG', 'vector search', 'vector database', 'vector db', 'retrieval', 'embeddings', 'semantic search', 'similarity search', 'knowledge base', 'nearest neighbor'],
    Icon: WeaviateIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(WeaviateNodeComponent),
};
