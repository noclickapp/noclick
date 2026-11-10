// Magento 2.X's self-discovered canvas and integration catalog definition.
// The icon is vendored from Magento's own repository with provenance beside it.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MagentoV2Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/magento-v2.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MagentoV2Node: NodeDefinition = {
    type: 'automation-magento-v2', category: 'ecommerce', label: 'Magento 2.X',
    description: 'Manage Magento products, customers, orders, invoices and shipments',
    keywords: ['Magento', 'Adobe Commerce', 'ecommerce', 'orders', 'catalog'],
    Icon: MagentoV2Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MagentoV2Icon} iconColor="" />),
};
