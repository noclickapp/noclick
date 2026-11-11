import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RumbleIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <>
        <img
            src="/icons/rumble.svg"
            alt=""
            className={`${className ?? ''} dark:hidden`}
            style={style}
        />
        <img
            src="/icons/rumble-dark.svg"
            alt=""
            className={`${className ?? ''} hidden dark:block`}
            style={style}
        />
    </>
);

export const RumbleNode: NodeDefinition = {
    type: 'automation-rumble',
    category: 'monitoring',
    label: 'Rumble API (deprecated)',
    description:
        'Manage network assets, sites and inventory with the frozen Rumble API, now runZero.',
    keywords: ['runZero', 'network discovery', 'asset inventory'],
    Icon: RumbleIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={RumbleIcon} iconColor="" />
    )),
};
