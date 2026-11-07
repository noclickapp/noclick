// Google Looker BI automation node definition.
// Provides workflow integration with the Looker API 4.0 (queries, Looks,
// dashboards, users, scheduled plans).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const LookerIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/looker.svg" alt="" className={className} style={style} {...props} />
));
LookerIcon.displayName = 'LookerIcon';

const LookerNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={LookerIcon} iconColor="" />;
};

export const LookerNode: NodeDefinition = {
    type: 'automation-looker',
    label: 'Google Looker',
    description: 'Google Looker BI automation',
    Icon: LookerIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(LookerNodeComponent),
};
