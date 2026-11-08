import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const InvoiceNinjaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/invoiceninja-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const InvoiceNinjaNode: NodeDefinition = {
    type: 'automation-invoiceninja',
    label: 'Invoice Ninja',
    description: 'Create clients and invoices, convert quotes, record payments, and sync products',
    category: 'finance-accounting',
    Icon: InvoiceNinjaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InvoiceNinjaIcon} iconColor="" />),
};
