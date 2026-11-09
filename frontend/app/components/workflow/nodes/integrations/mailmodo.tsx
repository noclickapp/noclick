// Mailmodo's self-registering workflow definition exposes its contact and campaign tools.
// The official brand asset identifies the connected email marketing service.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MailmodoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mailmodo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MailmodoNode: NodeDefinition = {
    type: 'automation-mailmodo', category: 'marketing', label: 'Mailmodo',
    description: 'Manage contacts, send campaigns, record events and start or abort journeys',
    Icon: MailmodoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MailmodoIcon} iconColor="" />),
};
