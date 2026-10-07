// OpenStatus metadata node uses its exact official published vector asset.
// Native forms and selection come from the generated typed schema; no generic RPC editor.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

export const OpenStatusIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/openstatus.svg" alt="" className={className} style={style} {...props} />,
);
OpenStatusIcon.displayName = 'OpenStatusIcon';
export const OpenStatusNode: NodeDefinition = {
    type: 'automation-openstatus', label: 'OpenStatus', description: 'Protected monitoring and status-page metadata reads',
    Icon: OpenStatusIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OpenStatusIcon} iconColor="" />,
};
