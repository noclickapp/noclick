import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PlanetScaleIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/planetscale.svg" dark="/icons/planetscale-dark.svg" className={className} style={style} />
);

export const PlanetScaleNode: NodeDefinition = {
    type: 'automation-planetscale',
    category: 'databases-storage',
    label: 'PlanetScale',
    description: 'Manage databases, branches, backups and deploy requests',
    Icon: PlanetScaleIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PlanetScaleIcon} iconColor="" />
    )),
};
