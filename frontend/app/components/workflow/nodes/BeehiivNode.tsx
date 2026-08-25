// beehiiv newsletter automation node definition.
// Provides workflow integration with the beehiiv v2 API (publications,
// subscriptions, posts, segments, automations) plus a webhook trigger.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BeehiivIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/beehiiv.svg" alt="" className={className} style={style} {...props} />
));
BeehiivIcon.displayName = 'BeehiivIcon';

const BeehiivNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BeehiivIcon} iconColor="" />;
};

export const BeehiivNode: NodeDefinition = {
    type: 'automation-beehiiv',
    label: 'beehiiv',
    description: 'beehiiv newsletter automation',
    Icon: BeehiivIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BeehiivNodeComponent),
};
