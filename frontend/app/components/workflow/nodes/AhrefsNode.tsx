// Ahrefs SEO automation node definition.
// Provides workflow integration with the Ahrefs API v3 (Site Explorer, Keywords
// Explorer, SERP, Batch Analysis, Site Audit, Rank Tracker, Management).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AhrefsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/ahrefs.svg" alt="" className={className} style={style} {...props} />
));
AhrefsIcon.displayName = 'AhrefsIcon';

const AhrefsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={AhrefsIcon} iconColor="" />;
};

export const AhrefsNode: NodeDefinition = {
    type: 'automation-ahrefs',
    label: 'Ahrefs',
    description: 'Ahrefs SEO automation',
    Icon: AhrefsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AhrefsNodeComponent),
};
