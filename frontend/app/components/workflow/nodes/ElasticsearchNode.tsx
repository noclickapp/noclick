// Elasticsearch vector database node definition.
// Provides workflow integration for kNN vector search, index/bulk/get/delete
// documents, and index management via the Elasticsearch REST API. Part of the
// external vector-database node set.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

const ElasticsearchIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/elasticsearch.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
ElasticsearchIcon.displayName = 'ElasticsearchIcon';

const ElasticsearchNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ElasticsearchIcon} iconColor="" iconSize={68} />;
};

export const ElasticsearchNode: NodeDefinition = {
    type: 'automation-elasticsearch',
    label: 'Elasticsearch',
    description: 'Search & vectors',
    keywords: ['RAG', 'vector search', 'vector database', 'vector db', 'retrieval', 'embeddings', 'semantic search', 'similarity search', 'knowledge base', 'nearest neighbor'],
    Icon: ElasticsearchIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ElasticsearchNodeComponent),
};
