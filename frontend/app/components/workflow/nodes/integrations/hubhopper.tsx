import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HubhopperIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/hubhopper.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={style}
    />
);

export const HubhopperNode: NodeDefinition = {
    type: 'automation-hubhopper',
    category: 'media',
    label: 'Hubhopper',
    description:
        'Browse partner podcasts, episodes, categories and languages, and watch for new content',
    keywords: ['podcast', 'audio', 'episodes', 'partner'],
    Icon: HubhopperIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={HubhopperIcon} iconColor="" />
    )),
};
