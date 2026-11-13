import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const ExLibrisIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/exlibrisgroup.svg" dark="/icons/exlibrisgroup-dark.svg" className={className} style={style} />
);

export const ExLibrisNode: NodeDefinition = {
    type: 'automation-exlibrisgroup',
    category: 'industry',
    label: 'Ex Libris APIs',
    description:
        'Automate Alma authority control tasks, printouts, shelf requests and lending queues',
    keywords: [
        'Alma',
        'library',
        'Ex Libris',
        'Clarivate',
        'authority control',
    ],
    Icon: ExLibrisIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ExLibrisIcon} iconColor="" />
    )),
};
