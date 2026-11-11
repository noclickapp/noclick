// BlueSky automation node definition.
// Uses AutomationNode component with BlueSky-specific configuration.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const BlueskyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bluesky.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BlueSkyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BlueskyIcon} iconColor="" />;
};

export const BlueSkyNode: NodeDefinition = {
    type: 'automation-bluesky',
    label: 'BlueSky',
    description: 'BlueSky automation',
    Icon: BlueskyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BlueSkyNodeComponent),
};
