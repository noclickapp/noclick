// Native Cliniko business, availability and external-contact workflow node.
// Uses the vendor's logo and the shared typed automation renderer.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const ClinikoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/cliniko.svg" alt="" className={className} style={style} {...props} />
);
ClinikoIcon.displayName = 'ClinikoIcon';

export const ClinikoNode: NodeDefinition = {
  type: 'automation-cliniko',
  label: 'Cliniko',
  description: 'Business, practitioner and availability metadata; external contacts',
  Icon: ClinikoIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClinikoIcon} iconColor="" />),
};
