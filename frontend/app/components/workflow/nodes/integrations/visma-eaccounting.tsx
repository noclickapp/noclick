import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const VismaEAccountingIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/visma-eaccounting.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
VismaEAccountingIcon.displayName = 'VismaEAccountingIcon';

export const VismaEAccountingNode: NodeDefinition = {
    type: 'automation-visma-eaccounting',
    label: 'Visma eAccounting',
    description: 'Manage customers, articles, suppliers and customer invoices',
    category: 'finance-accounting',
    keywords: ['Visma', 'eAccounting', 'Spiris', 'invoicing', 'accounting'],
    Icon: VismaEAccountingIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VismaEAccountingIcon} iconColor="" />),
};
