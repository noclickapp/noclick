import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MxTechnologiesIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/mx-technologies.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MxTechnologiesIcon.displayName = 'MxTechnologiesIcon';

export const MxTechnologiesNode: NodeDefinition = {
    type: 'automation-mx-technologies',
    label: 'MX Technologies',
    description: 'Manage financial users and members, aggregate accounts, and read and update transactions',
    category: 'finance-accounting',
    keywords: ['MX', 'banking', 'financial data', 'aggregation', 'transactions'],
    Icon: MxTechnologiesIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MxTechnologiesIcon} iconColor="" />),
};
