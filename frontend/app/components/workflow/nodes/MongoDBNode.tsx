// MongoDB database automation node definition.
// Covers CRUD, aggregation, index management, Atlas Vector Search, and document upload/indexing for RAG.
// Part of the database + vector-DB node set.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 44 };

const MongoDBIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/mongodb.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
MongoDBIcon.displayName = 'MongoDBIcon';

const MongoDBNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MongoDBIcon} iconColor="" iconSize={52} />;
};

export const MongoDBNode: NodeDefinition = {
    type: 'automation-mongodb',
    label: 'MongoDB',
    description: 'MongoDB database',
    keywords: ['database', 'nosql', 'mongodb', 'atlas', 'vector search', 'RAG', 'document store', 'aggregation', 'embeddings', 'semantic search'],
    Icon: MongoDBIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MongoDBNodeComponent),
};
