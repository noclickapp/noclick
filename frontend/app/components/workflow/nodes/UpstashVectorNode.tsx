// Upstash Vector database node definition.
// Provides workflow integration for serverless vector search/upsert (vector and
// text-in via server-side embedding), fetch, delete, and info via the Upstash
// Vector REST API. Part of the external vector-database node set.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

const UpstashVectorIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/upstash-vector.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
UpstashVectorIcon.displayName = 'UpstashVectorIcon';

const UpstashVectorNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={UpstashVectorIcon} iconColor="" iconSize={56} />;
};

export const UpstashVectorNode: NodeDefinition = {
    type: 'automation-upstash-vector',
    label: 'Upstash Vector',
    description: 'Vector database',
    keywords: ['RAG', 'vector search', 'vector database', 'vector db', 'retrieval', 'embeddings', 'semantic search', 'similarity search', 'knowledge base', 'nearest neighbor'],
    Icon: UpstashVectorIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(UpstashVectorNodeComponent),
};
