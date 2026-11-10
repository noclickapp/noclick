import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const BolnaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/bolna.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/bolna-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} />
    </>
);
export const BolnaNode: NodeDefinition = {
    type: 'automation-bolna', category: 'ai', label: 'Bolna',
    description: 'Manage voice agents, place calls, and read executions, batches and knowledge bases',
    Icon: BolnaIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BolnaIcon} iconColor="" />),
};
