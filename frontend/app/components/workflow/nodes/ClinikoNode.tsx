// Native Cliniko business, availability and external-contact workflow node.
// Uses the vendor's logo and the shared typed automation renderer.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';


// Unmodified compact brand asset from https://www.cliniko.com/
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/cliniko-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const ClinikoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/cliniko.svg" alt="" className={className} style={style} {...props} />
);
ClinikoIcon.displayName = 'ClinikoIcon';

export const ClinikoNode: NodeDefinition = {
  type: 'automation-cliniko',
  label: 'Cliniko',
  description: 'Business, practitioner and availability metadata; external contacts',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
