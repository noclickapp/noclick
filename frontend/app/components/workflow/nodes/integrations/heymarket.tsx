// Exposes Heymarket SMS in the canvas and integration catalog.
// Its schema and account connection are discovered from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const HeymarketIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/heymarket.svg" dark="/icons/heymarket-dark.svg" className={className} style={style} />
);

export const HeymarketNode: NodeDefinition = {
    type: 'automation-heymarket', category: 'communication', label: 'Heymarket SMS',
    description: 'Send SMS and MMS, sync contacts, and manage conversations and lists',
    keywords: ['Heymarket', 'SMS', 'MMS', 'text message', 'shared inbox'],
    Icon: HeymarketIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HeymarketIcon} iconColor="" />),
};
