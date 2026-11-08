import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RilletIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rillet.svg" alt="" aria-hidden="true" className={['brand-mono', className].filter(Boolean).join(' ')}
        style={{ ...style, objectFit: 'contain', filter: 'invert(1) ' + (style?.filter || 'invert(var(--brand-invert, 0))') } as CSSProperties} />
);

export const RilletNode: NodeDefinition = {
    type: 'automation-rillet', category: 'finance-accounting', label: 'Rillet',
    description: 'Sync accounting records and create customers, vendors, invoices, bills and journal entries',
    keywords: ['accounting', 'ERP', 'accounts receivable', 'accounts payable', 'general ledger'],
    Icon: RilletIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RilletIcon} iconColor="" />),
};
