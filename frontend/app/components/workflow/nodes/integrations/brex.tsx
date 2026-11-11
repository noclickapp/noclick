// Brex's canvas definition is discovered from its integration filename.
// Its component loads only when a Brex node appears on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Unmodified Brex symbol from Brex's official press kit.
const BrexIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/brex.svg" dark="/icons/brex-dark.svg" className={className} style={style} />
);

const BrexNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BrexIcon} iconColor="" />
);

export const BrexNode: NodeDefinition = {
    type: 'automation-brex',
    label: 'Brex',
    description: 'Manage expenses, cards and transfers; trigger workflows from expense payments and processed transfers',
    category: 'finance-accounting',
    keywords: [
        'expenses',
        'corporate cards',
        'payments',
        'transactions',
        'transfers',
    ],
    Icon: BrexIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(BrexNodeComponent),
};
