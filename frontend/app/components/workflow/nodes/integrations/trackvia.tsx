import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TrackViaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/trackvia.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TrackViaNode: NodeDefinition = {
    type: 'automation-trackvia', category: 'databases-storage', label: 'TrackVia',
    description: 'Read and manage TrackVia records, views, users and microservices',
    Icon: TrackViaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TrackViaIcon} iconColor="" />),
};
