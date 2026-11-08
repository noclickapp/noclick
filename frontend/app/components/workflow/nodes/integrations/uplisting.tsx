import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UplistingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/uplisting.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const UplistingNode: NodeDefinition = {
    type: 'automation-uplisting', label: 'Uplisting',
    description: 'Manage properties, availability, calendars, bookings, custom attributes and webhooks',
    Icon: UplistingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UplistingIcon} iconColor="" />),
};
