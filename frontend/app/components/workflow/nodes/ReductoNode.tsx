// Reducto document intelligence automation node definition.
// Provides workflow integration with the Reducto REST API (parse, extract,
// split, classify, edit, pipeline, jobs) plus a webhook trigger for completed
// async jobs.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ReductoIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/reducto.svg" alt="" className={className} style={style} {...props} />
));
ReductoIcon.displayName = 'ReductoIcon';

const ReductoNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ReductoIcon} iconColor="" />;
};

export const ReductoNode: NodeDefinition = {
    type: 'automation-reducto',
    label: 'Reducto',
    description: 'Reducto document intelligence automation',
    Icon: ReductoIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ReductoNodeComponent),
};
