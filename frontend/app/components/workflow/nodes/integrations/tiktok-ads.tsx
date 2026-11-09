import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TikTokAdsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tiktok-ads.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TikTokAdsNode: NodeDefinition = {
    type: 'automation-tiktok-ads', category: 'marketing', label: 'TikTok Ads',
    description: 'Manage Smart+ campaigns, ad groups, ads, audiences, pixels and performance reports',
    keywords: ['TikTok for Business', 'advertising', 'paid social', 'Smart Plus'],
    Icon: TikTokAdsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TikTokAdsIcon} iconColor="" />),
};
