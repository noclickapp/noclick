// Inbound-email trigger node definition.
// Entry point for workflows triggered by email sent to a reserved address (localpart@noclick.app).
// Uses the shared AutomationNode component with a mail icon; config UI is the email_trigger widget.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';
import { MailArrowIn } from '~/components/icons/MailArrowIn';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const InboundEmailTriggerNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MailArrowIn} iconColor="text-foreground" />;
};

export const InboundEmailTriggerNode: NodeDefinition = {
    type: 'trigger-email',
    label: 'Get Email',
    description: 'Inbound Email',
    keywords: ['email', 'inbound email', 'incoming mail', 'receive email', 'mailbox', 'inbox', 'on email received', 'forward email'],
    Icon: MailArrowIn,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(InboundEmailTriggerNodeComponent),
};
