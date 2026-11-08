import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const ZohoProjectsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/zoho-projects.svg"
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

const ZohoProjectsNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ZohoProjectsIcon} iconColor="" />
);

export const ZohoProjectsNode: NodeDefinition = {
    type: 'automation-zoho-projects',
    label: 'Zoho Projects',
    description: 'Manage projects, task lists and tasks',
    Icon: ZohoProjectsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ZohoProjectsNodeComponent),
};
