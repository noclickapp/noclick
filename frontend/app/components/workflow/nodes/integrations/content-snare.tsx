import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ContentSnareIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/content-snare.svg"
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

export const ContentSnareNode: NodeDefinition = {
    type: 'automation-content-snare',
    category: 'documents',
    label: 'Content Snare',
    description:
        'Manage clients, collect requests, review fields and find templates',
    Icon: ContentSnareIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function ContentSnareComponent(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={ContentSnareIcon} iconColor="" />
        );
    }),
};
