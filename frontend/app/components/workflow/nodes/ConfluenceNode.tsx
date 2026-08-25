// Confluence workflow node component.
// Provides Confluence Cloud automation (pages, blog posts, spaces, comments,
// attachments, labels, content properties, CQL search) via the REST API.
// Supports OAuth 2.0 (3LO) and Basic-auth (email + API token) credentials.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiConfluence } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ConfluenceNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiConfluence} iconColor="#1868DB" />;
};

export const ConfluenceNode: NodeDefinition = {
    type: 'automation-confluence',
    label: 'Confluence',
    description: 'Confluence Cloud automation',
    Icon: SiConfluence,
    iconColor: '#1868DB',
    dimensions: DIMENSIONS,
    component: memo(ConfluenceNodeComponent),
};
