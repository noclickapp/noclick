// Zoom meetings, webinars, users, and cloud-recording automation node.
// Provides workflow integration with the Zoom v2 REST API plus a webhook
// trigger for Zoom event notifications.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ZoomIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/zoom.svg" alt="" className={className} style={style} {...props} />
));
ZoomIcon.displayName = 'ZoomIcon';

const ZoomNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ZoomIcon} iconColor="" />;
};

export const ZoomNode: NodeDefinition = {
    type: 'automation-zoom',
    label: 'Zoom',
    description: 'Zoom meetings, webinars, users, and recordings automation',
    Icon: ZoomIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ZoomNodeComponent),
};
