import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://printify.com/press-kit/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/printify-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const PrintifyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/printify.svg" alt="" className={className} style={style} {...props} />
  ),
);
PrintifyIcon.displayName = 'PrintifyIcon';

export const PrintifyNode: NodeDefinition = {
  type: 'automation-printify',
  label: 'Printify',
  description: 'Shop and catalog metadata, products, and product descriptions; also supports the shared Printful Enterprise API',
  category: 'ecommerce',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
