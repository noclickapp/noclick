import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JustOneApiIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/just-one-api.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const JustOneApiNode: NodeDefinition = {
    type: 'automation-just-one-api',
    category: 'content-research',
    label: 'Just One API',
    description:
        'Collect social content, research products and convert sourcing images',
    keywords: [
        'JustOneAPI',
        'RedNote',
        'Xiaohongshu',
        'Douyin',
        'WeChat',
        'Taobao',
        '1688',
    ],
    Icon: JustOneApiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={JustOneApiIcon} iconColor="" />
    )),
};
