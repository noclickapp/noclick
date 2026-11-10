import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const MercadoPagoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/mercado-pago.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MercadoPagoIcon.displayName = 'MercadoPagoIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const MercadoPagoNode: NodeDefinition = {
    type: 'automation-mercado-pago',
    label: 'Mercado Pago',
    description: 'Payments, refunds, checkout, customers and subscriptions',
    category: 'finance-accounting',
    Icon: MercadoPagoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MercadoPagoIcon} iconColor="" />),
};
