// GoCardless's account automation definition is discovered without a shared registry entry.
// The publisher's symbol identifies this integration in the canvas and catalog.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const GoCardlessIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/gocardless.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
GoCardlessIcon.displayName = 'GoCardlessIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const GoCardlessNode: NodeDefinition = {
    type: 'automation-gocardless',
    label: 'GoCardless',
    description: 'Customers, mandates, payments, subscriptions, refunds and payouts',
    category: 'finance-accounting',
    Icon: GoCardlessIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoCardlessIcon} iconColor="" />),
};
