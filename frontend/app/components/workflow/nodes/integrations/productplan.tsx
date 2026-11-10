// ProductPlan native roadmap, strategy, discovery and launch metadata operations.
// The shared automation form renders typed fields and scoped resource pickers.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://productplan.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/productplan-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const ProductPlanNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const ProductPlanNode: NodeDefinition = {
  type: 'automation-productplan', category: 'productivity', label: 'ProductPlan',
  description: 'Read roadmap, strategy and launch metadata; manage parked bars',
  Icon: OfficialBrandIcon, iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: ProductPlanNodeComponent,
};
