// RSS feed automation node definition.
// Uses AutomationNode component with RSS-specific configuration.
// Supports multiple RSS feed services (Miniflux, Feedly, FreshRSS, RSS.app) and direct feed parsing.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const RssIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rss.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const RSSNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={RssIcon} iconColor="" />;
};

export const RSSNode: NodeDefinition = {
    type: 'automation-rss',
    label: 'RSS',
    description: 'RSS feed automation',
    Icon: RssIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(RSSNodeComponent),
};
