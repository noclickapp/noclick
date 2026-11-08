import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AxonautIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/axonaut.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
AxonautIcon.displayName = 'AxonautIcon';

const AxonautNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={AxonautIcon} iconColor="" />
);

export const AxonautNode: NodeDefinition = {
    type: 'automation-axonaut',
    label: 'Axonaut',
    description: 'Axonaut CRM, contacts, tasks and projects',
    Icon: AxonautIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AxonautNodeComponent),
};
