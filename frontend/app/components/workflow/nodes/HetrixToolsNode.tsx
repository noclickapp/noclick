// Native HetrixTools metadata node for the workflow canvas.
// Uses the original vendor PNG; operation forms come from the native generated schema.
import React, { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
const HetrixToolsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/hetrixtools.png" alt="" className={className} style={style} {...props} />,
);
HetrixToolsIcon.displayName = 'HetrixToolsIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={HetrixToolsIcon} iconColor="" />;
export const HetrixToolsNode: NodeDefinition = {
  type: 'automation-hetrixtools', label: 'HetrixTools',
  description: 'Read protected v3 scope, uptime, downtime, status-page and maintenance metadata',
  keywords: ['HetrixTools', 'uptime', 'monitor', 'downtime', 'status page', 'maintenance', 'metadata'],
  Icon: HetrixToolsIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(Component),
};
