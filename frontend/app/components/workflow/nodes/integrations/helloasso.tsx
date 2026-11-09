// HelloAsso brings association fundraising and payment operations to workflows.
// Its backend schema supplies the operation forms and manual token connection.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HelloAssoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/helloasso.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const HelloAssoNode: NodeDefinition = {
    type: 'automation-helloasso', category: 'nonprofit', label: 'HelloAsso',
    description: 'Manage association forms, orders, payments, participants and checkouts',
    keywords: ['association', 'donations', 'fundraising', 'memberships', 'tickets'],
    Icon: HelloAssoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HelloAssoIcon} iconColor="" />),
};
