import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/followupboss.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const FollowUpBossNode: NodeDefinition = {
    type: 'automation-followupboss', label: 'Follow Up Boss', category: 'crm-sales',
    description: 'Manage people, stages, notes and tasks, and receive signed CRM events',
    Icon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Icon} iconColor="" />),
};
