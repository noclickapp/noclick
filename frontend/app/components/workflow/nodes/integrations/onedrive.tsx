// Microsoft OneDrive automation node definition.
// Provides comprehensive OneDrive file operations via Microsoft Graph API.
// Supports files, folders, sharing, permissions, versions, thumbnails, and search.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Microsoft OneDrive 2025 icon SVG
const OneDriveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/onedrive.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const OneDriveNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={OneDriveIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const OneDriveNode: NodeDefinition = {
    type: 'automation-onedrive',
    label: 'OneDrive',
    description: 'OneDrive automation',
    Icon: OneDriveIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(OneDriveNodeComponent),
};
