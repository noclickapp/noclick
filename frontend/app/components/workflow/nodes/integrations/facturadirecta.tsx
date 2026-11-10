// FacturaDirecta's native integration catalog and canvas definition.
// Generated schemas supply the operation and credential forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FacturaDirectaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/facturadirecta.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const FacturaDirectaNode: NodeDefinition = {
    type: 'automation-facturadirecta', category: 'finance-accounting', label: 'FacturaDirecta',
    description: 'Manage contacts, products, invoices, payments, estimates and purchase bills',
    keywords: ['accounting', 'invoicing', 'facturas', 'presupuestos'],
    Icon: FacturaDirectaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FacturaDirectaIcon} iconColor="" />),
};
