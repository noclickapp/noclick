/* Reclaim AI is discovered through this integration-local definition.
   The canvas and integration directory share its icon and productivity category. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ReclaimAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/reclaim-ai.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/reclaim-ai-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const ReclaimAINode: NodeDefinition = {
    type: 'automation-reclaim-ai', category: 'productivity', label: 'Reclaim AI',
    description: 'Manage Reclaim tasks and smart habits, and read calendars',
    keywords: ['reclaim', 'reclaim.ai', 'calendar', 'tasks', 'habits', 'scheduling'],
    Icon: ReclaimAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReclaimAIIcon} iconColor="" />),
};
