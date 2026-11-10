import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const NewieIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/newie.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
NewieIcon.displayName = 'NewieIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const NewieNode: NodeDefinition = {
    type: 'automation-newie',
    label: 'Newie',
    description: 'Customers, offerings, subscriptions, payments and metadata',
    category: 'finance-accounting',
    Icon: NewieIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NewieIcon} iconColor="" />),
};
