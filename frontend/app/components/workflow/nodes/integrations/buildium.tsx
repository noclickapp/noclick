import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BuildiumIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/buildium.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
BuildiumIcon.displayName = 'BuildiumIcon';

const BuildiumNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BuildiumIcon} iconColor="" />
);

export const BuildiumNode: NodeDefinition = {
    type: 'automation-buildium',
    label: 'Buildium',
    description: 'Buildium property metadata, notes and task categories',
    Icon: BuildiumIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BuildiumNodeComponent),
};
