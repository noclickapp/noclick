// Google Display & Video 360 (DV360) automation node definition.
// Provides workflow integration with the DV360 v4 API (advertisers, campaigns,
// insertion orders, line items, creatives, targeting, channels, audiences) plus
// the Bid Manager reporting API.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DV360Icon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/dv360.svg" alt="" className={className} style={style} {...props} />
));
DV360Icon.displayName = 'DV360Icon';

const DV360NodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={DV360Icon} iconColor="" />;
};

export const DV360Node: NodeDefinition = {
    type: 'automation-dv360',
    label: 'Google DV360',
    description: 'Google Display & Video 360 ad management',
    Icon: DV360Icon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(DV360NodeComponent),
};
