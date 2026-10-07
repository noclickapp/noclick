import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const StatusPalIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/statuspal.png" alt="" className={className} style={style} {...props} />
);
StatusPalIcon.displayName = 'StatusPalIcon';
const StatusPalNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={StatusPalIcon} iconColor="" />;
export const StatusPalNode: NodeDefinition = {
    type: 'automation-statuspal', label: 'StatusPal',
    description: 'StatusPal protected status-page and service metadata reads',
    Icon: StatusPalIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: StatusPalNodeComponent,
};
