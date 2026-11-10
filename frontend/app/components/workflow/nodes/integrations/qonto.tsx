import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const QontoIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/qonto.svg" dark="/icons/qonto-dark.svg" className={className} style={style} />
);

export const QontoNode: NodeDefinition = {
    type: 'automation-qonto',
    category: 'finance-accounting',
    label: 'Qonto',
    description:
        'Start workflows from Qonto transaction and invoice events; automate account reporting and bookkeeping',
    Icon: QontoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={QontoIcon} iconColor="" />
    )),
};
