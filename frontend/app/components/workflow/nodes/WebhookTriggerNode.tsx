// Webhook trigger node definition.
// This node acts as an entry point for workflows triggered by external HTTP webhooks.
// Uses AutomationNode component with webhook-specific configuration.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Webhook } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const WebhookTriggerNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={Webhook} iconColor="text-foreground" />;
};

export const WebhookTriggerNode: NodeDefinition = {
    type: 'trigger-webhook',
    label: 'Webhook',
    description: 'HTTP Webhook',
    keywords: ['webhook', 'http', 'https', 'endpoint', 'url', 'callback', 'incoming request', 'post request', 'api call', 'curl'],
    Icon: Webhook,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(WebhookTriggerNodeComponent),
};
