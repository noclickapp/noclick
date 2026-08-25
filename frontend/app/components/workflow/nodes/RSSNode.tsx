// RSS feed automation node definition.
// Uses AutomationNode component with RSS-specific configuration.
// Supports multiple RSS feed services (Miniflux, Feedly, FreshRSS, RSS.app) and direct feed parsing.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiRss } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const RSSNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiRss} iconColor="text-orange-500" />;
};

export const RSSNode: NodeDefinition = {
    type: 'automation-rss',
    label: 'RSS',
    description: 'RSS feed automation',
    Icon: SiRss,
    iconColor: 'text-orange-500',
    dimensions: DIMENSIONS,
    component: memo(RSSNodeComponent),
};
