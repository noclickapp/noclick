// Milvus / Zilliz Cloud vector database node definition.
// Provides workflow integration for vector search, insert/upsert/query/delete,
// and collection management via the Milvus REST v2 API. Part of the external
// vector-database node set.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

const MilvusIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/milvus.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
MilvusIcon.displayName = 'MilvusIcon';

const MilvusNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MilvusIcon} iconColor="" iconSize={56} />;
};

export const MilvusNode: NodeDefinition = {
    type: 'automation-milvus',
    label: 'Milvus',
    description: 'Vector database',
    keywords: ['RAG', 'vector search', 'vector database', 'vector db', 'retrieval', 'embeddings', 'semantic search', 'similarity search', 'knowledge base', 'nearest neighbor'],
    Icon: MilvusIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MilvusNodeComponent),
};
