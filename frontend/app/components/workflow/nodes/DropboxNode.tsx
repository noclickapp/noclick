// Dropbox automation node definition.
// Provides workflow integration with Dropbox API for file storage, sharing, and collaboration.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const DropboxIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/dropbox.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
DropboxIcon.displayName = 'DropboxIcon';

const DropboxNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={DropboxIcon} iconColor="" />;
};

export const DropboxNode: NodeDefinition = {
    type: 'automation-dropbox',
    label: 'Dropbox',
    description: 'Dropbox automation',
    Icon: DropboxIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(DropboxNodeComponent),
};
