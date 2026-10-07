// Registers DNSimple's account-scoped metadata reads on the workflow canvas.
// The generated backend schema supplies operation forms and credentials.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';
import DNSimpleIcon from '~/components/icons/DNSimpleIcon';
const DNSimpleNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={DNSimpleIcon as any} iconColor="" />
);
export const DNSimpleNode: NodeDefinition = {
    type: 'automation-dnsimple', label: 'DNSimple',
    description: 'Account-scoped domain and zone metadata without DNS records or control',
    keywords: ['DNSimple', 'domain state', 'zone metadata', 'expiry', 'DNS account'],
    Icon: DNSimpleIcon as any, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: DNSimpleNodeComponent,
};

