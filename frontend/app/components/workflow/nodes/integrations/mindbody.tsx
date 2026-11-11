// Mindbody's native Public API v6 metadata and client management node.
// The complete official wordmark is displayed without cropping or recoloring.
// Client writes start in validation mode and do not imply a booking or payment.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


// Mindbody's favicon M from https://www.mindbodyonline.com/; source and edits are in its provenance file.
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/mindbody-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const MindbodyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <img {...props} ref={ref} src="/icons/mindbody.svg" alt="" className={className}
      style={{ ...style, width: 76, height: 28, objectFit: 'contain' }} />
  ),
);
MindbodyIcon.displayName = 'MindbodyIcon';

export const MindbodyNode: NodeDefinition = {
  type: 'automation-mindbody',
  label: 'Mindbody',
  description: 'Read business metadata and manage client profiles and preferences',
  category: 'bookings',
  keywords: ['fitness', 'wellness', 'staff', 'clients', 'classes', 'appointments'],
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
