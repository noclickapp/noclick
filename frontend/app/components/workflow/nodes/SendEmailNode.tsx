// Send-email node definition.
// Emails the running user's own account address (self-notification only) — the
// recipient is resolved server-side and is deliberately not configurable.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';
import { MailArrowRight } from '~/components/icons/MailArrowRight';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const SendEmailNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MailArrowRight} iconColor="text-foreground" />;
};

export const SendEmailNode: NodeDefinition = {
    type: 'automation-send-email',
    label: 'Send Email',
    description: 'Email yourself',
    Icon: MailArrowRight,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(SendEmailNodeComponent),
};
