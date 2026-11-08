import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DubIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
  <img src="/icons/dub-preferred-brand.svg" alt="" aria-hidden="true" className={className}
    style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const DubNode: NodeDefinition = {
  type: 'automation-dub',
  label: 'Dub',
  description: 'Protected domain and link metadata with destination URLs omitted',
  category: 'marketing',
  Icon: DubIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: (props: NodeProps) => <AutomationNode {...props} Icon={DubIcon} iconColor="" />,
};
