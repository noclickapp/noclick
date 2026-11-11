// LinkedIn automation node definition.
// Uses LinkedIn REST API for posting, profile retrieval, and content management.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 58 };

// Inline SVG component for instant rendering (no network request/pop-in)
const LinkedInIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/linkedin.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const LinkedInNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={LinkedInIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const LinkedInNode: NodeDefinition = {
    type: 'automation-linkedin',
    label: 'LinkedIn',
    description: 'LinkedIn automation',
    Icon: LinkedInIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(LinkedInNodeComponent),
};
