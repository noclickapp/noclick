// Box content-management automation node definition.
// Provides workflow integration with the Box Content API v2.0 (files, folders,
// sharing, collaboration, comments, tasks, search, webhooks) plus a webhook
// trigger for file/folder events. Added to surface Box as a workflow node.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BoxIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/box.svg" alt="" className={className} style={style} {...props} />
));
BoxIcon.displayName = 'BoxIcon';

const BoxNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BoxIcon} iconColor="" />;
};

export const BoxNode: NodeDefinition = {
    type: 'automation-box',
    label: 'Box',
    description: 'Box content management automation',
    Icon: BoxIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BoxNodeComponent),
};
