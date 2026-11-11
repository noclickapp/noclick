import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SuprSendIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/suprsend.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const SuprSendNode: NodeDefinition = {
    type: 'automation-suprsend',
    label: 'SuprSend',
    category: 'communication',
    description: 'Send notifications, manage users, lists, tenants and preferences, and watch new messages',
    keywords: ['notifications', 'email', 'sms', 'inbox', 'push'],
    Icon: SuprSendIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SuprSendIcon} iconColor="" />),
};
