// Reddit workflow node component.
// Provides Reddit API operations in visual workflow editor.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Reddit Snoo icon (official Reddit logo)
const RedditIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/reddit.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const RedditNode: NodeDefinition = {
    type: 'automation-reddit',
    label: 'Reddit',
    description: 'Reddit automation',
    Icon: RedditIcon as any,
    iconColor: '', // Custom SVG, no Tailwind color needed
    dimensions: DIMENSIONS,
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={RedditIcon as any} iconColor="" />
    )),
};
