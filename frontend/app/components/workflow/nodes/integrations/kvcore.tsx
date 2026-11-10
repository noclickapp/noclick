// kvCORE's catalog and canvas definition uses the official provider mark.
// The backend supplies the operation and credential forms through generated schemas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KvcoreIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kvcore.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const KvcoreNode: NodeDefinition = {
    type: 'automation-kvcore', category: 'crm-sales', label: 'kvCORE',
    description: 'Manage real estate contacts, tags, notes and calls; read users, alerts and listing summaries',
    keywords: ['kvcore', 'real estate', 'Inside Real Estate', 'CRM'],
    Icon: KvcoreIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KvcoreIcon} iconColor="" />),
};
