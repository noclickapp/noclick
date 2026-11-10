import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TeamworkIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/teamwork.svg" dark="/icons/teamwork-dark.svg" className={className} style={style} {...props} ref={ref} />
));
TeamworkIcon.displayName = 'TeamworkIcon';

const TeamworkNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={TeamworkIcon} iconColor="" />
);

export const TeamworkNode: NodeDefinition = {
    type: 'automation-teamwork',
    label: 'Teamwork',
    category: 'productivity',
    description: 'Teamwork project and task automation',
    Icon: TeamworkIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(TeamworkNodeComponent),
};
