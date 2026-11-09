import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TwittershotsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/twittershots.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TwittershotsNode: NodeDefinition = {
    type: 'automation-twittershots',
    category: 'social-media',
    label: 'TwitterShots',
    description: 'Generate Twitter/X tweet screenshots and check API quota',
    keywords: ['Twittershots', 'tweet', 'screenshot', 'X'],
    Icon: TwittershotsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TwittershotsIcon} iconColor="" />),
};
