// Webflow CMS / site automation node definition.
// Provides workflow integration with the Webflow Data API v2 (sites, pages,
// CMS collections & items, forms, assets, ecommerce, comments, webhooks) plus
// a webhook trigger for Webflow events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const WebflowIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/webflow.svg" alt="" className={className} style={style} {...props} />
));
WebflowIcon.displayName = 'WebflowIcon';

const WebflowNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={WebflowIcon} iconColor="" />;
};

export const WebflowNode: NodeDefinition = {
    type: 'automation-webflow',
    label: 'Webflow',
    description: 'Webflow CMS and site automation',
    Icon: WebflowIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(WebflowNodeComponent),
};
