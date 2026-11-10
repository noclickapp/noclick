import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CatsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/cats.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const CatsNode: NodeDefinition = {
    type: 'automation-cats',
    label: 'CATS',
    category: 'hr-recruiting',
    description:
        'Manage recruiting records and start workflows when candidates arrive or pipeline statuses change',
    keywords: ['catsone', 'recruiting', 'applicant tracking'],
    Icon: CatsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={CatsIcon} iconColor="" />
    )),
};
