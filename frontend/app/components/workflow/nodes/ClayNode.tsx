import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const ClayIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/clay.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
ClayIcon.displayName = 'ClayIcon';

export const ClayNode: NodeDefinition = {
    type: 'automation-clay',
    label: 'Clay',
    description: 'Search GTM data, run enrichments, and query Clay tables',
    Icon: ClayIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ClayIcon} iconColor="" />
    )),
};
