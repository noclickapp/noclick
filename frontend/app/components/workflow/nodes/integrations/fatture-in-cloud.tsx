import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FattureInCloudIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/fatture-in-cloud.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FattureInCloudNode: NodeDefinition = {
    type: 'automation-fatture-in-cloud', category: 'finance-accounting', label: 'Fatture in Cloud',
    description: 'Manage clients, suppliers, products and invoices; read received documents and companies; start workflows from invoice, contact and product events',
    keywords: ['fatture', 'invoices', 'Italian accounting'],
    Icon: FattureInCloudIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FattureInCloudIcon} iconColor="" />),
};
