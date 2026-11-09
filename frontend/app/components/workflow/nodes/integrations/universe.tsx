import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UniverseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/universe.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const UniverseNode: NodeDefinition = {
    type: 'automation-universe', category: 'bookings', label: 'Universe',
    description: 'Read guestlists and listings, check in tickets, and create rates and discount codes',
    Icon: UniverseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UniverseIcon} iconColor="" />),
};
