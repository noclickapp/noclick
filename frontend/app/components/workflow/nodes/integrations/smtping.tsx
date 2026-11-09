// Adds Smtping to the workflow canvas and integration catalog.
// Uses the official brand icon and the marketing category for email list hygiene.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SmtpingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smtping.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SmtpingNode: NodeDefinition = {
    type: 'automation-smtping', category: 'marketing', label: 'Smtping',
    description: 'Verify emails, clean lists, detect risky addresses and track credits',
    keywords: ['SMTPing', 'email verification', 'spamtrap', 'disposable email'],
    Icon: SmtpingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SmtpingIcon} iconColor="" />),
};
