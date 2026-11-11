import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PidgeonIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => (
    <>
      <img {...props} ref={ref} src="/icons/pidgeon.svg" alt="" className={`dark:hidden ${className ?? ''}`} style={style} />
      <img {...props} src="/icons/pidgeon-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
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
