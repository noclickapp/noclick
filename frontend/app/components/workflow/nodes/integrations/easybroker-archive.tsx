import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EasyBrokerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/easybroker-archive.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EasyBrokerNode: NodeDefinition = {
    type: 'automation-easybroker-archive', category: 'crm-sales', label: 'EasyBroker',
    description: 'Manage real estate properties, contacts and lead requests; watch for new leads and updates.',
    keywords: ['real estate', 'property', 'leads', 'easybroker'],
    Icon: EasyBrokerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 60 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EasyBrokerIcon} iconColor="" />),
};
