import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';
import STACKITDNSIcon from '~/components/icons/STACKITDNSIcon';
const STACKITDNSNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={STACKITDNSIcon as any} iconColor="" />
);
export const STACKITDNSNode: NodeDefinition = {
    type: 'automation-stackitdns', label: 'STACKIT DNS',
    description: 'Protected zone and RRset metadata without DNS record values or changes',
    keywords: ['STACKIT DNS', 'zone metadata', 'RRset status', 'DNS metadata'],
    Icon: STACKITDNSIcon as any, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: STACKITDNSNodeComponent,
};
