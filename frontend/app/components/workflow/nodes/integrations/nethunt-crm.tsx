import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NetHuntCrmIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/nethunt-crm.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const NetHuntCrmNode: NodeDefinition = {
    type: 'automation-nethunt-crm', category: 'crm-sales', label: 'NetHunt CRM',
    description: 'Manage folders, records, comments, calls and timelines',
    Icon: NetHuntCrmIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NetHuntCrmIcon} iconColor="" />),
};
