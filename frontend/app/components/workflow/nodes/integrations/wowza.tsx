// Adds Wowza to the integration catalog and workflow canvas. The official symbol identifies its streaming and video operations.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WowzaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wowza.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const WowzaNode: NodeDefinition = {
    type: 'automation-wowza', category: 'media', label: 'Wowza',
    description: 'Control live streams and recordings, manage videos and schedules, and watch for new videos',
    Icon: WowzaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WowzaIcon} iconColor="" />),
};
