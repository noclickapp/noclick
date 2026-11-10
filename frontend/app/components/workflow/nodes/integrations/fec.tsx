import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const FECIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/fec.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
  ),
);
FECIcon.displayName = 'FECIcon';

export const FECNode: NodeDefinition = {
  type: 'automation-fec',
  label: 'OpenFEC',
  description: 'Search campaign finance data and watch new federal election filings',
  category: 'content-research',
  Icon: FECIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 64 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FECIcon} iconColor="" />),
};
