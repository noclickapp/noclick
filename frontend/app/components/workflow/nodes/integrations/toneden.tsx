// Registers ToneDen in the integration catalog and workflow canvas.
// The shared automation node renders its generated operation schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TonedenIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/toneden.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const TonedenNode: NodeDefinition = {
    type: 'automation-toneden',
    category: 'marketing',
    label: 'ToneDen',
    description: 'Manage links, campaigns, contests and social unlocks',
    Icon: TonedenIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={TonedenIcon} iconColor="" />
    )),
};
