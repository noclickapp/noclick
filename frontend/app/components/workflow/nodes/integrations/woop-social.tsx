import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WoopSocialIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/woop-social.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const WoopSocialNode: NodeDefinition = {
    type: 'automation-woop-social', category: 'social-media', label: 'Woop Social',
    description: 'Schedule posts and manage projects, social accounts, media and webhooks',
    Icon: WoopSocialIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WoopSocialIcon} iconColor="" />),
};
