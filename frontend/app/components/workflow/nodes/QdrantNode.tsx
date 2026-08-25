// Qdrant vector database node definition.
// Provides workflow integration for vector similarity search, upsert, retrieve,
// delete, and collection management via the Qdrant REST API. Part of the
// external vector-database node set for agent + dataflow retrieval.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

const QdrantIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/qdrant.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
QdrantIcon.displayName = 'QdrantIcon';

const QdrantNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={QdrantIcon} iconColor="" iconSize={56} />;
};

export const QdrantNode: NodeDefinition = {
    type: 'automation-qdrant',
    label: 'Qdrant',
    description: 'Vector database',
    keywords: ['RAG', 'vector search', 'vector database', 'vector db', 'retrieval', 'embeddings', 'semantic search', 'similarity search', 'knowledge base', 'nearest neighbor'],
    Icon: QdrantIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(QdrantNodeComponent),
};
