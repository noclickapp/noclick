// Registers the Hello Tracks integration in the canvas and service catalog.
// Uses the official publisher icon to identify field service automations.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HelloTracksIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hello-tracks.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const HelloTracksNode: NodeDefinition = {
    type: 'automation-hello-tracks',
    category: 'industry',
    label: 'Hello Tracks',
    description: 'Automate field jobs, places, routes, timesheets and forms',
    keywords: ['hellotracks', 'dispatch', 'field service', 'fleet', 'geofencing'],
    Icon: HelloTracksIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HelloTracksIcon} iconColor="" />),
};
