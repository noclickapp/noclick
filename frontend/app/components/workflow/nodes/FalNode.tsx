// fal.ai model-inference automation node definition.
// Provides workflow integration with the fal.ai platform (run models sync/queue,
// poll status, fetch results, storage, platform management) plus a webhook
// trigger for queued-job completion events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FalIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/fal.svg" alt="" className={className} style={style} {...props} />
));
FalIcon.displayName = 'FalIcon';

const FalNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={FalIcon} iconColor="" />;
};

export const FalNode: NodeDefinition = {
    type: 'automation-fal',
    label: 'fal',
    description: 'fal.ai model inference automation',
    Icon: FalIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FalNodeComponent),
};
