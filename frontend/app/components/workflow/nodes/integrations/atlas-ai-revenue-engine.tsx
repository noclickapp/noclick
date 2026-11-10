import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AtlasIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/atlas-ai-revenue-engine.svg" dark="/icons/atlas-ai-revenue-engine-dark.svg" className={className} style={style} />
);

export const AtlasAIRevenueEngineNode: NodeDefinition = {
    type: 'automation-atlas-ai-revenue-engine', category: 'crm-sales', label: 'Atlas AI Revenue Engine',
    description: 'Manage contacts and campaigns, schedule calls and SMS, and read conversations and bookings',
    keywords: ['youratlas', 'voice AI', 'outbound calls', 'SMS', 'sales'],
    Icon: AtlasIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AtlasIcon} iconColor="" />),
};
