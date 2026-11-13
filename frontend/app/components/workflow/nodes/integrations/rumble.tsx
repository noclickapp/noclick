import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const RumbleIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/rumble.svg" dark="/icons/rumble-dark.svg" className={className} style={style} />
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
