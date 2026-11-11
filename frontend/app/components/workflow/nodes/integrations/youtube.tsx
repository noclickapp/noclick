// YouTube automation node definition.
// Uses AutomationNode component with YouTube-specific configuration.
// Enables interacting with YouTube Data API via Google OAuth credentials.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Custom YouTube icon component that renders the multi-colored SVG
const YouTubeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/youtube.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const YouTubeNodeComponent = (props: NodeProps) => {
    // Pass empty iconColor since the SVG has its own colors
    return <AutomationNode {...props} Icon={YouTubeIcon as any} iconColor="" />;
};

export const YouTubeNode: NodeDefinition = {
    type: 'automation-youtube',
    label: 'YouTube',
    description: 'YouTube automation',
    Icon: YouTubeIcon as any,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(YouTubeNodeComponent),
};
