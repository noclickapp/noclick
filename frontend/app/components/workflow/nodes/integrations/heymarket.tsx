// Exposes Heymarket SMS in the canvas and integration catalog.
// Its schema and account connection are discovered from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HeymarketIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/heymarket.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const HeymarketNode: NodeDefinition = {
    type: 'automation-heymarket', category: 'communication', label: 'Heymarket SMS',
    description: 'Send SMS and MMS, sync contacts, and manage conversations and lists',
    keywords: ['Heymarket', 'SMS', 'MMS', 'text message', 'shared inbox'],
    Icon: HeymarketIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HeymarketIcon} iconColor="" />),
};
