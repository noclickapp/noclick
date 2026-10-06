// ProductPlan native roadmap, strategy, discovery and launch metadata operations.
// The shared automation form renders typed fields and scoped resource pickers.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const ProductPlanIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/productplan.svg" alt="" className={className}
      style={{ backgroundColor: 'white', padding: 4, objectFit: 'contain', ...style }} {...props} />
  ),
);
ProductPlanIcon.displayName = 'ProductPlanIcon';
const ProductPlanNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={ProductPlanIcon} iconColor="" />;

export const ProductPlanNode: NodeDefinition = {
  type: 'automation-productplan', label: 'ProductPlan',
  description: 'Read roadmap, strategy and launch metadata; manage parked bars',
  Icon: ProductPlanIcon, iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: ProductPlanNodeComponent,
};
