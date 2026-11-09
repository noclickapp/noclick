// REI Pebble's self-registering catalog and canvas definition.
// The provider's official icon identifies its property and deal automation tools.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PebbleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rei-pebble.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const REIPebbleNode: NodeDefinition = {
    type: 'automation-rei-pebble', category: 'industry', label: 'REI Pebble',
    description: 'Manage real estate contacts, properties, deals, tasks and tags',
    keywords: ['Pebble', 'real estate', 'land investing', 'CRM'],
    Icon: PebbleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PebbleIcon} iconColor="" />),
};
