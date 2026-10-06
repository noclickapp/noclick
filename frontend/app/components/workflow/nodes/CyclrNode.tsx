// Cyclr reads selected-account workflow and catalog metadata through closed routes.
// The shared editor uses its native schema and performs no cycle execution.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const CyclrIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/cyclr.svg" alt="" className={className} style={{ backgroundColor: '#222', borderRadius: 4, ...style }} {...props} />
  ),
);
CyclrIcon.displayName = 'CyclrIcon';
const CyclrNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={CyclrIcon} iconColor="" />;

export const CyclrNode: NodeDefinition = {
  type: 'automation-cyclr',
  label: 'Cyclr',
  description: 'Selected-account cycle, template and catalog metadata',
  Icon: CyclrIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo(CyclrNodeComponent),
};
