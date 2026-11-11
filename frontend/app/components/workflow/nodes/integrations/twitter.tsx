// Twitter/X REST API v2 automation node definition.
// Provides workflow integration for Twitter/X with tweets, users, likes, retweets, follows, and more.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const XIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/twitter.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/twitter-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TwitterNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={XIcon} iconColor="" />;
};

export const TwitterNode: NodeDefinition = {
    type: 'automation-twitter',
    label: 'X',
    description: 'Twitter/X automation',
    Icon: XIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(TwitterNodeComponent),
};
