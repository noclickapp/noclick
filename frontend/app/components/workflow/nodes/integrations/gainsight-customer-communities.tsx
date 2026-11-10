import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const GainsightCustomerCommunitiesIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/gainsight-customer-communities.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/gainsight-customer-communities-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
GainsightCustomerCommunitiesIcon.displayName = 'GainsightCustomerCommunitiesIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const GainsightCustomerCommunitiesNode: NodeDefinition = {
    type: 'automation-gainsight-customer-communities',
    label: 'Gainsight Customer Communities',
    description: 'Read community content, start conversations, ask questions and manage tags',
    category: 'support',
    Icon: GainsightCustomerCommunitiesIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GainsightCustomerCommunitiesIcon} iconColor="" />),
};
