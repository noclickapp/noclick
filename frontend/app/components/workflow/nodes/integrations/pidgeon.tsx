import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const PidgeonIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <ThemedBrandImg {...props} ref={ref} light="/icons/pidgeon.svg" dark="/icons/pidgeon-dark.svg" className={className} style={style} />
  ),
);
PidgeonIcon.displayName = 'PidgeonIcon';

export const PidgeonNode: NodeDefinition = {
  type: 'automation-pidgeon',
  label: 'Pidgeon',
  description: 'Receive email, send replies, manage inboxes, threads and drafts',
  category: 'communication',
  keywords: ['email', 'inbox', 'agent mail', 'webhook'],
  Icon: PidgeonIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 64 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PidgeonIcon} iconColor="" />),
};
