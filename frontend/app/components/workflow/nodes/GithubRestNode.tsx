// GitHub REST API automation node definition.
// Uses direct REST API calls for optimal performance (~200ms vs ~65s for MCP).

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiGithub } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GithubRestNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiGithub} iconColor="text-foreground" />;
};

export const GithubRestNode: NodeDefinition = {
    type: 'automation-github-rest',
    label: 'GitHub',
    description: 'Github automation',
    Icon: SiGithub,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(GithubRestNodeComponent),
};
