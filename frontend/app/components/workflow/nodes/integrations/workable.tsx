import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const WorkableIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/workable.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
WorkableIcon.displayName = 'WorkableIcon';

export const WorkableNode: NodeDefinition = {
    type: 'automation-workable',
    label: 'Workable',
    description: 'Hiring, candidates, employees, and time off',
    category: 'hr-recruiting',
    Icon: WorkableIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => (
        <AutomationNode {...props} Icon={WorkableIcon} iconColor="" />
    ),
};
