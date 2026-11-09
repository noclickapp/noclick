import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AppointeddIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/appointedd.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AppointeddNode: NodeDefinition = {
    type: 'automation-appointedd', category: 'bookings', label: 'Appointedd',
    description: 'Automate bookings, customers, availability, events, services and resources',
    Icon: AppointeddIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AppointeddIcon} iconColor="" />),
};
