// Exposes Dynatrace's account-management actions and audit trigger in the workflow catalog.
// Discovery loads this definition without adding shared registration entries.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DynatraceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dynatrace.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const DynatraceNode: NodeDefinition = {
    type: 'automation-dynatrace',
    category: 'monitoring',
    label: 'Dynatrace',
    description: 'Manage account users, groups, IAM policies and audit events',
    keywords: ['account management', 'IAM', 'observability', 'audit logs'],
    Icon: DynatraceIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DynatraceIcon} iconColor="" />),
};
