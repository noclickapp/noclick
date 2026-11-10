// Registers Aryeo in the workflow palette and integration catalog.
// Uses the provider icon to identify its real estate automation operations.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AryeoIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/aryeo.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const AryeoNode: NodeDefinition = {
    type: 'automation-aryeo',
    category: 'industry',
    label: 'Aryeo',
    description:
        'Manage real estate listings, orders, appointments and scheduling',
    Icon: AryeoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={AryeoIcon} iconColor="" />
    )),
};
