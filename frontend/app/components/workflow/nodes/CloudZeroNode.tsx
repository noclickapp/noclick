import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const CloudZeroIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/cloudzero.svg" alt="" className={className} style={style} {...props} />
);
CloudZeroIcon.displayName = 'CloudZeroIcon';
const CloudZeroNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={CloudZeroIcon} iconColor="" />;
export const CloudZeroNode: NodeDefinition = {
    type: 'automation-cloudzero', label: 'CloudZero',
    description: 'CloudZero cost, dimension and saved-view metadata reads',
    Icon: CloudZeroIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: CloudZeroNodeComponent,
};
