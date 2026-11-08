import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AblyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/ably.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
AblyIcon.displayName = 'AblyIcon';

const AblyNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={AblyIcon} iconColor="" />
);

export const AblyNode: NodeDefinition = {
    type: 'automation-ably',
    label: 'Ably',
    description: 'Ably realtime messaging and push automation',
    category: 'communication',
    Icon: AblyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AblyNodeComponent),
};
