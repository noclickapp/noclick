// Cyclr reads selected-account workflow and catalog metadata through closed routes.
// The shared editor uses its native schema and performs no cycle execution.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://cyclr.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/cyclr-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const CyclrIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/cyclr.svg" alt="" className={className} style={{ backgroundColor: '#222', borderRadius: 4, ...style }} {...props} />
  ),
);
CyclrIcon.displayName = 'CyclrIcon';
const CyclrNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const CyclrNode: NodeDefinition = {
  type: 'automation-cyclr',
  label: 'Cyclr',
  description: 'Selected-account cycle, template and catalog metadata',
  category: 'developer-tools',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo(CyclrNodeComponent),
};
