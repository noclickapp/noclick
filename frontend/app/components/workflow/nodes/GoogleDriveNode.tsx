// Google Drive automation node definition.
// Uses AutomationNode component with Google Drive-specific configuration.
// Enables file operations on Google Drive via OAuth credentials.

import { memo, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Inline SVG component for instant rendering (no network request/pop-in)
const GoogleDriveIcon = ({ className, style, ...props }: SVGProps<SVGSVGElement>) => (
    <svg
        viewBox="0 -3 48 48"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        style={style}
        {...props}
    >
        <polygon fill="#3777E3" points="8.00048064 42 15.9998798 28 48 28 39.9998798 42" />
        <polygon fill="#FFCF63" points="32.0004806 28 48 28 32.0004806 0 15.9998798 0" />
        <polygon fill="#11A861" points="0 28 8.00048064 42 24 14 15.9998798 0" />
    </svg>
);

const GoogleDriveNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleDriveIcon as any} iconColor="" />;
};

export const GoogleDriveNode: NodeDefinition = {
    type: 'automation-google-drive',
    label: 'Google Drive',
    description: 'Google Drive files',
    Icon: GoogleDriveIcon as any,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleDriveNodeComponent),
};
