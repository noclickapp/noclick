// ProductPlan native roadmap, strategy, discovery and launch metadata operations.
// The shared automation form renders typed fields and scoped resource pickers.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';


// Unmodified compact brand asset from https://www.productplan.com/
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/productplan-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const ProductPlanIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/productplan.svg" alt="" className={className}
      style={{ backgroundColor: 'white', padding: 4, objectFit: 'contain', ...style }} {...props} />
  ),
);
ProductPlanIcon.displayName = 'ProductPlanIcon';
const ProductPlanNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const ProductPlanNode: NodeDefinition = {
  type: 'automation-productplan', label: 'ProductPlan',
  description: 'Read roadmap, strategy and launch metadata; manage parked bars',
  Icon: OfficialBrandIcon, iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: ProductPlanNodeComponent,
};
