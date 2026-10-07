// Native Exoscale APIv2 metadata node for the workflow canvas.
// The original official icon is rendered unchanged; forms use the native generated schema.
import React, { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
const ExoscaleIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/exoscale.svg" alt="" className={className} style={style} {...props} />,
);
ExoscaleIcon.displayName = 'ExoscaleIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={ExoscaleIcon} iconColor="" />;
export const ExoscaleNode: NodeDefinition = {
  type: 'automation-exoscale', label: 'Exoscale',
  description: 'Read signed APIv2 zone-local instance, capacity and anti-affinity metadata',
  keywords: ['Exoscale', 'cloud', 'compute', 'instance', 'capacity', 'anti-affinity', 'metadata'],
  Icon: ExoscaleIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(Component),
};
