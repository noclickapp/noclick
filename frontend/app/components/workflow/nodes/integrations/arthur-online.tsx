// Arthur Online's discoverable workflow node and catalog entry.
// The official icon identifies its property management actions and poll triggers.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ArthurOnlineIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/arthur-online.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ArthurOnlineNode: NodeDefinition = {
    type: 'automation-arthur-online', category: 'industry', label: 'Arthur Online',
    description: 'Manage properties, units, certificates, contacts, notes and quotes',
    keywords: ['property management', 'landlord', 'lettings', 'workorders'],
    Icon: ArthurOnlineIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ArthurOnlineIcon} iconColor="" />),
};
