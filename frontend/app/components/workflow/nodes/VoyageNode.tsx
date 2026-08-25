// Voyage AI embedding and reranking node definition.
// Provides workflow integration with the Voyage AI API for generating
// dense text embeddings and cross-encoder reranking for RAG pipelines.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const VoyageIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/voyage.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
VoyageIcon.displayName = 'VoyageIcon';

const VoyageNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={VoyageIcon} iconColor="" />;
};

export const VoyageNode: NodeDefinition = {
    type: 'automation-voyage',
    label: 'Voyage AI',
    description: 'Text embeddings and reranking',
    keywords: [
        'embed', 'embeddings', 'vectorize', 'vector', 'encode', 'semantic',
        'RAG', 'retrieval', 'rerank', 'reranking', 'cross-encoder', 'relevance',
        'voyage', 'dense', 'representation', 'similarity',
    ],
    Icon: VoyageIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(VoyageNodeComponent),
};
