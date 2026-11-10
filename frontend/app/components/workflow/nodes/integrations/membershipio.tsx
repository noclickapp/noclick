import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const MembershipioIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/membershipio.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/membershipio-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
MembershipioIcon.displayName = 'MembershipioIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const MembershipioNode: NodeDefinition = {
    type: 'automation-membershipio',
    label: 'Membership.io',
    keywords: ['Searchie', 'membership', 'audience', 'courses'],
    description: 'Manage audience members, hub access, tags, attributes and content',
    category: 'courses',
    Icon: MembershipioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MembershipioIcon} iconColor="" />),
};
