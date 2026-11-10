import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DynamicMockupsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/dynamic-mockups.svg" dark="/icons/dynamic-mockups-dark.svg" className={className} style={style} />
);

export const DynamicMockupsNode: NodeDefinition = {
    type: 'automation-dynamic-mockups',
    category: 'media',
    label: 'Dynamic Mockups',
    description:
        'Render mockups, manage catalogs and collections, upload PSDs and generate AI images and videos',
    keywords: [
        'dynamicmockups',
        'mockanything',
        'motionmockups',
        'PSD',
        'print on demand',
    ],
    Icon: DynamicMockupsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={DynamicMockupsIcon} iconColor="" />
    )),
};
