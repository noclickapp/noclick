import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ExLibrisIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <>
        <img
            src="/icons/exlibrisgroup.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} dark:hidden`}
            style={style}
        />
        <img
            src="/icons/exlibrisgroup-dark.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} hidden dark:block`}
            style={style}
        />
    </>
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
