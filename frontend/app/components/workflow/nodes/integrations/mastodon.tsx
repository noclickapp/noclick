import { ComponentProps } from 'react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const Icon = ({ className, style }: ComponentProps<'svg'>) => (
  <img src="/icons/mastodon.svg" alt="" className={className} style={style} />
);

export const MastodonNode: NodeDefinition = {
  type: 'automation-mastodon',
  label: 'Mastodon',
  description: 'Read your verified account and authored status metadata without post content',
  Icon: Icon as NodeDefinition['Icon'],
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: props => <AutomationNode {...props} Icon={Icon as NodeDefinition['Icon']} iconColor="" />,
};
