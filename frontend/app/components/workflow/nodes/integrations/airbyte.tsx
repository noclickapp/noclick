// Airbyte Configuration API actions and scheduled sync-job events.
// The original publisher icon identifies this self-hosted API integration.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AirbyteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/airbyte.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AirbyteNode: NodeDefinition = {
    type: 'automation-airbyte', label: 'Airbyte Configuration API', category: 'databases-storage',
    description: 'Manage self-hosted sources, destinations and connections, run syncs, and watch new sync jobs.',
    keywords: ['Airbyte', 'ETL', 'ELT', 'data integration', 'replication', 'sync'],
    Icon: AirbyteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AirbyteIcon} iconColor="" />),
};
