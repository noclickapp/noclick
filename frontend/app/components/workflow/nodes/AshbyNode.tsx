import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const AshbyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/ashby.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
AshbyIcon.displayName = 'AshbyIcon';

export const AshbyNode: NodeDefinition = {
    type: 'automation-ashby',
    label: 'Ashby',
    description: 'Manage candidates, applications, jobs, and job postings',
    Icon: AshbyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={AshbyIcon} iconColor="" />
    )),
};
