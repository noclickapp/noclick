// Registers Encharge in the workflow canvas and integration catalog.
// Uses the official brand icon and the marketing category for discovery.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EnchargeIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/encharge.png"
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

export const EnchargeNode: NodeDefinition = {
    type: 'automation-encharge',
    category: 'marketing',
    label: 'Encharge',
    description: 'Manage people, tags, segments and person fields',
    keywords: ['email marketing', 'contacts', 'customer segmentation'],
    Icon: EnchargeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function EnchargeCanvas(props: NodeProps) {
        return <AutomationNode {...props} Icon={EnchargeIcon} iconColor="" />;
    }),
};
