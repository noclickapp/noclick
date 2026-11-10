import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RingoverIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ringover.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RingoverNode: NodeDefinition = {
    type: 'automation-ringover', category: 'communication', label: 'Ringover',
    description: 'Automate calls, SMS, contacts and call events',
    Icon: RingoverIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RingoverIcon} iconColor="" />),
};
