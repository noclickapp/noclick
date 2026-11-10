import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ChorusByZoomInfoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/chorus-by-zoominfo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ChorusByZoomInfoNode: NodeDefinition = {
    type: 'automation-chorus-by-zoominfo', category: 'crm-sales', label: 'Chorus by ZoomInfo',
    description: 'Automate recordings, users, teams, playlists, moments and webhooks',
    Icon: ChorusByZoomInfoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ChorusByZoomInfoIcon} iconColor="" />),
};
