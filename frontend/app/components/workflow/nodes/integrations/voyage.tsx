// Voyage AI embedding and reranking node definition.
// Provides workflow integration with the Voyage AI API for generating
// dense text embeddings and cross-encoder reranking for RAG pipelines.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const VoyageIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/voyage.svg" dark="/icons/voyage-dark.svg" ref={ref} className={className} style={style} />
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
