import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const InvoiceXpressIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/invoicexpress.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
InvoiceXpressIcon.displayName = 'InvoiceXpressIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const InvoiceXpressNode: NodeDefinition = {
    type: 'automation-invoicexpress',
    label: 'InvoiceXpress',
    description: 'Invoices, payments, clients, items, taxes and sequences',
    category: 'finance-accounting',
    Icon: InvoiceXpressIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InvoiceXpressIcon} iconColor="" />),
};
