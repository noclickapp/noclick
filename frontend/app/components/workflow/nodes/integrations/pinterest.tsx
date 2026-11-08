// Pinterest's canvas definition is discovered from its integration filename.
// Its component loads only when a Pinterest node appears on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Pinterest brand mark from Simple Icons (CC0).
const PinterestIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/pinterest.svg"
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

const PinterestNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PinterestIcon} iconColor="" />
);

export const PinterestNode: NodeDefinition = {
    type: 'automation-pinterest',
    label: 'Pinterest',
    description: 'Pinterest pins, boards, ads, catalogs, and analytics',
    category: 'social-media',
    Icon: PinterestIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(PinterestNodeComponent),
};
