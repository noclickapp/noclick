import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MailerSendIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mailersend.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MailerSendNode: NodeDefinition = {
    type: 'automation-mailersend', label: 'MailerSend',
    description: 'Send email and manage messages, recipients and suppressions',
    Icon: MailerSendIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MailerSendIcon} iconColor="" />),
};
