import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TeamworkIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/teamwork.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
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
