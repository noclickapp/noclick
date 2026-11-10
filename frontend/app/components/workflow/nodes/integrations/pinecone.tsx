// Pinecone vector database node definition.
// Provides workflow integration for vector similarity search, upsert, fetch, delete,
// and index management via the Pinecone API. Added as part of the external
// vector-database node set so agents and dataflows can do retrieval.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

const PineconeIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/pinecone-light.svg" dark="/icons/pinecone.svg" {...props} />
));
PineconeIcon.displayName = 'PineconeIcon';

const PineconeNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={PineconeIcon}
            iconColor=""
            iconSize={56}
        />
    );
};

export const PineconeNode: NodeDefinition = {
    type: 'automation-pinecone',
    label: 'Pinecone',
    description: 'Vector database',
    keywords: [
        'RAG',
        'vector search',
        'vector database',
        'vector db',
        'retrieval',
        'embeddings',
        'semantic search',
        'similarity search',
        'knowledge base',
        'nearest neighbor',
    ],
    Icon: PineconeIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PineconeNodeComponent),
};
