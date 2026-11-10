import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BlinqIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/blinq.svg" className={className} style={style} />
);

export const BlinqNode: NodeDefinition = {
    type: 'automation-blinq', category: 'crm-sales', label: 'Blinq',
    description: 'Read contacts, cards and notes, ask questions and manage webhook subscriptions',
    Icon: BlinqIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BlinqIcon} iconColor="" />),
};
