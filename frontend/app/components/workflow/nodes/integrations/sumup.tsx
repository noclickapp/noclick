import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

// Official SumUp Circuit design-system brand artwork; see asset-provenance.json.
const SumUpIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/sumup.svg" dark="/icons/sumup-dark.svg" ref={ref} className={className} style={{ ...style, objectFit: 'contain' }} />
    )
);
SumUpIcon.displayName = 'SumUpIcon';

export const SumUpNode: NodeDefinition = {
    type: 'automation-sumup',
    label: 'SumUp',
    description: 'Create payment checkouts, sync customers, retrieve transactions and refund payments',
    category: 'finance-accounting',
    keywords: ['payments', 'checkout', 'refund', 'customers', 'payouts', 'reconciliation'],
    Icon: SumUpIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SumUpIcon} iconColor="" />),
};
