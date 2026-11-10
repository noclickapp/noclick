// Displays Mihu Ai in the workflow canvas and integration catalog.
// The schema provides its token connection and operation forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MihuAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/mihu-ai.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/mihu-ai-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const MihuAiNode: NodeDefinition = {
    type: 'automation-mihu-ai', category: 'ai', label: 'Mihu Ai',
    description: 'Manage contacts, agents, calls, appointments and campaigns in Mihu Ai',
    Icon: MihuAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MihuAiIcon} iconColor="" />),
};
