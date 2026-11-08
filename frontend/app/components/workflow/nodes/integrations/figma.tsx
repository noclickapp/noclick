import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FigmaIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/figma-preferred-brand.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
FigmaIcon.displayName = 'FigmaIcon';

const FigmaNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={FigmaIcon} iconColor="" />
);

export const FigmaNode: NodeDefinition = {
    type: 'automation-figma',
    label: 'Figma',
    description: 'Figma files, comments, libraries, dev resources and webhooks',
    Icon: FigmaIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FigmaNodeComponent),
};
