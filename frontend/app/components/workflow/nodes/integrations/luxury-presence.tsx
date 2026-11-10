// Luxury Presence uses its official favicon to identify this integration.
// The node definition makes its generated operations available in the workflow catalog.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const LuxuryPresenceIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/luxury-presence.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/luxury-presence-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
LuxuryPresenceIcon.displayName = 'LuxuryPresenceIcon';

export const LuxuryPresenceNode: NodeDefinition = {
    type: 'automation-luxury-presence',
    label: 'Luxury Presence',
    description: 'Manage real estate agents, offices, teams, memberships, media and webhook subscriptions.',
    category: 'industry',
    keywords: ['real estate', 'agents', 'brokerage', 'luxury presence'],
    Icon: LuxuryPresenceIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LuxuryPresenceIcon} iconColor="" />),
};
