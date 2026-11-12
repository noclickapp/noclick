import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SmallImprovementsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/small-improvements.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const SmallImprovementsNode: NodeDefinition = {
    type: 'automation-small-improvements',
    category: 'hr-recruiting',
    label: 'Small Improvements',
    description:
        'Monitor praise, manage employees, track objectives and read performance reviews',
    keywords: [
        'performance management',
        'employee feedback',
        'praise',
        'objectives',
        'HR',
    ],
    Icon: SmallImprovementsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={SmallImprovementsIcon} iconColor="" />
    )),
};
