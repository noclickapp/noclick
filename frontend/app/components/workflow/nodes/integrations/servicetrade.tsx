// ServiceTrade's field-service operations use the shared automation node renderer.
// This definition makes the integration available in the canvas and industry catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ServiceTradeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/servicetrade.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ServiceTradeNode: NodeDefinition = {
    type: 'automation-servicetrade', category: 'industry', label: 'ServiceTrade',
    description: 'Start workflows when ServiceTrade records change; manage field-service jobs, appointments, contacts and locations',
    keywords: ['field service', 'contractor', 'technician', 'maintenance', 'dispatch'],
    Icon: ServiceTradeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ServiceTradeIcon} iconColor="" />),
};
