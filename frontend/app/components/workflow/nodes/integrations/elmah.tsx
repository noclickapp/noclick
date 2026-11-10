import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ElmahIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/elmah.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const ElmahNode: NodeDefinition = {
    type: 'automation-elmah',
    category: 'monitoring',
    label: 'elmah.io',
    description:
        'Monitor new errors, search and manage messages, logs, deployments and heartbeats',
    keywords: ['elmah', 'errors', 'logging', 'monitoring'],
    Icon: ElmahIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ElmahIcon} iconColor="" />
    )),
};
