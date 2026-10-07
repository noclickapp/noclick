// Native metadata reads with the unchanged PNG linked by Porkbun's official guide.
import { ComponentProps } from 'react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';
const Icon = ({ className, style }: ComponentProps<'svg'>) => (
  <img src="/icons/porkbun.png" alt="" className={className} style={style} />
);
export const PorkbunNode: NodeDefinition = {
  type: 'automation-porkbun',
  label: 'Porkbun',
  description: 'Read protected domain and DNS record metadata without DNS values',
  Icon: Icon as NodeDefinition['Icon'],
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: props => <AutomationNode {...props} Icon={Icon as NodeDefinition['Icon']} iconColor="" />,
};
