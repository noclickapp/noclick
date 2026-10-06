import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

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
  Icon: PrintifyIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PrintifyIcon} iconColor="" />),
};
