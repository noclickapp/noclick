// Fellow (fellow.ai) AI meeting assistant automation node definition.
// Provides workflow integration with the Fellow Developer REST API (recordings,
// notes, action items, webhooks) plus a webhook trigger for Fellow events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FellowIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/fellow.svg" alt="" className={className} style={style} {...props} />
));
FellowIcon.displayName = 'FellowIcon';

const FellowNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={FellowIcon} iconColor="" />;
};

export const FellowNode: NodeDefinition = {
    type: 'automation-fellow',
    label: 'Fellow',
    description: 'Fellow AI meeting assistant automation',
    Icon: FellowIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FellowNodeComponent),
};
