import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TikTokAdsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/tiktok-ads.svg" dark="/icons/tiktok-ads-dark.svg" className={className} style={style} />
);

export const TikTokAdsNode: NodeDefinition = {
    type: 'automation-tiktok-ads', category: 'marketing', label: 'TikTok Ads',
    description: 'Manage Smart+ campaigns, ad groups, ads, audiences, pixels and performance reports',
    keywords: ['TikTok for Business', 'advertising', 'paid social', 'Smart Plus'],
    Icon: TikTokAdsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TikTokAdsIcon} iconColor="" />),
};
