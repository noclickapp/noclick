import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const WebexIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/webex.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
WebexIcon.displayName = 'WebexIcon';

const WebexNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={WebexIcon} iconColor="" />
);

export const WebexNode: NodeDefinition = {
    type: 'automation-webex',
    label: 'Webex',
    description: 'Spaces, messages, teams, meetings, invitees, and recordings',
    Icon: WebexIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(WebexNodeComponent),
};
