import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const EvolizIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/evoliz.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
EvolizIcon.displayName = 'EvolizIcon';

export const EvolizNode: NodeDefinition = {
    type: 'automation-evoliz',
    label: 'Evoliz',
    description: 'Clients, invoices, quotes, articles, payments and change triggers',
    category: 'finance-accounting',
    keywords: ['accounting', 'invoicing', 'billing'],
    Icon: EvolizIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EvolizIcon} iconColor="" />),
};
