import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BookeoIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/bookeo.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
BookeoIcon.displayName = 'BookeoIcon';

const BookeoNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BookeoIcon} iconColor="" />
);

export const BookeoNode: NodeDefinition = {
    type: 'automation-bookeo',
    label: 'Bookeo',
    description: 'Bookeo bookings, customers and availability',
    Icon: BookeoIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BookeoNodeComponent),
};
