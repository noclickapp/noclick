import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WeezeventIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/weezevent-da56471.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WeezeventNode: NodeDefinition = {
    type: 'automation-weezevent-da56471', category: 'bookings', label: 'Weezevent',
    description: 'Manage events, rates, attendees, orders and ticket resale; watch attendee and order changes',
    Icon: WeezeventIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WeezeventIcon} iconColor="" />),
};
