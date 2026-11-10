/* Reclaim AI is discovered through this integration-local definition.
   The canvas and integration directory share its icon and productivity category. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ReclaimAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/reclaim-ai.svg" dark="/icons/reclaim-ai-dark.svg" className={className} style={style} />
);

export const ReclaimAINode: NodeDefinition = {
    type: 'automation-reclaim-ai', category: 'productivity', label: 'Reclaim AI',
    description: 'Manage Reclaim tasks and smart habits, and read calendars',
    keywords: ['reclaim', 'reclaim.ai', 'calendar', 'tasks', 'habits', 'scheduling'],
    Icon: ReclaimAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReclaimAIIcon} iconColor="" />),
};
