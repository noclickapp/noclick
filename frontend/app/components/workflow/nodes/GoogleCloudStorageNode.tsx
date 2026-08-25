// Google Cloud Storage automation node definition.
// Provides workflow integration with the Google Cloud Storage JSON API v1
// (buckets, objects, IAM, notifications, projects).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GoogleCloudStorageIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-cloud-storage.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleCloudStorageIcon.displayName = 'GoogleCloudStorageIcon';

const GoogleCloudStorageNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleCloudStorageIcon} iconColor="" />;
};

export const GoogleCloudStorageNode: NodeDefinition = {
    type: 'automation-google-cloud-storage',
    label: 'Google Cloud Storage',
    description: 'Google Cloud Storage automation',
    Icon: GoogleCloudStorageIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleCloudStorageNodeComponent),
};
