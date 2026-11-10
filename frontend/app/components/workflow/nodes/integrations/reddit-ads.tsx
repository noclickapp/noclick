// Reddit Ads automation appears in the marketing catalog and workflow canvas.
// The icon comes from the provider's API documentation and is reviewed in its sidecar.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RedditAdsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/reddit-ads.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
export const RedditAdsNode: NodeDefinition = {
    type: 'automation-reddit-ads', category: 'marketing', label: 'Reddit Ads',
    description: 'Manage campaigns, ad groups and ads, and report on advertising performance',
    Icon: RedditAdsIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RedditAdsIcon} iconColor="" />),
};
