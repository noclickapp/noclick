import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const MediaSiloIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/mediasilo.svg" alt="" className={className} style={style} {...props} />
);
MediaSiloIcon.displayName = 'MediaSiloIcon';
const MediaSiloNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={MediaSiloIcon} iconColor="" />;
export const MediaSiloNode: NodeDefinition = {
    type: 'automation-mediasilo', label: 'MediaSilo',
    description: 'MediaSilo protected project and folder metadata reads',
    Icon: MediaSiloIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: MediaSiloNodeComponent,
};
