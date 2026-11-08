import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const FinmoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/finmo.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FinmoIcon.displayName = 'FinmoIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const FinmoNode: NodeDefinition = {
    type: 'automation-finmo',
    label: 'Finmo',
    category: 'finance-accounting',
    description: 'Customers, payins, payouts, refunds, wallets and transactions',
    Icon: FinmoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FinmoIcon} iconColor="" />),
};
