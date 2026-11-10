// Campaign Cleaner automates campaign cleaning and inbox placement monitoring.
// This definition lets the self-registering catalog and canvas discover the integration.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CampaignCleanerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/campaign-cleaner.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CampaignCleanerNode: NodeDefinition = {
    type: 'automation-campaign-cleaner',
    category: 'marketing',
    label: 'Campaign Cleaner',
    description: 'Clean email HTML, analyze campaigns, test inbox placement and manage monitoring alerts',
    keywords: ['email', 'deliverability', 'spam', 'inbox placement'],
    Icon: CampaignCleanerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CampaignCleanerIcon} iconColor="" />),
};
