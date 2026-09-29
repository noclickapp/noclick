import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const ConnecteamIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/connecteam.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
ConnecteamIcon.displayName = 'ConnecteamIcon';

export const ConnecteamNode: NodeDefinition = {
    type: 'automation-connecteam',
    label: 'Connecteam',
    description: 'Workforce scheduling, time tracking, tasks, forms, and users',
    Icon: ConnecteamIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => (
        <AutomationNode {...props} Icon={ConnecteamIcon} iconColor="" />
    ),
};
