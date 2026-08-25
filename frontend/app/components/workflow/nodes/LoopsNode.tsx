// Loops email marketing & lifecycle automation node definition.
// Provides workflow integration with the Loops API (contacts, events,
// transactional emails, campaigns, mailing lists).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const LoopsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/loops.svg" alt="" className={className} style={style} {...props} />
));
LoopsIcon.displayName = 'LoopsIcon';

const LoopsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={LoopsIcon} iconColor="" />;
};

export const LoopsNode: NodeDefinition = {
    type: 'automation-loops',
    label: 'Loops',
    description: 'Loops email marketing & lifecycle automation',
    Icon: LoopsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(LoopsNodeComponent),
};
