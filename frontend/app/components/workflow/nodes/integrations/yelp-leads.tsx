import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const YelpLeadsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/yelp-leads.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
YelpLeadsIcon.displayName = 'YelpLeadsIcon';

export const YelpLeadsNode: NodeDefinition = {
    type: 'automation-yelp-leads',
    label: 'Yelp Leads',
    description: 'Read leads, reply to customers, and mark conversations read or replied',
    category: 'crm-sales',
    keywords: ['Yelp', 'leads', 'quotes', 'customer messages'],
    Icon: YelpLeadsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={YelpLeadsIcon} iconColor="" />),
};
