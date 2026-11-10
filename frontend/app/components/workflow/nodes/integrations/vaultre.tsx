import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VaultREIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/vaultre.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const VaultRENode: NodeDefinition = {
    type: 'automation-vaultre', category: 'crm-sales', label: 'VaultRE',
    description: 'Manage real estate contacts, notes and tasks; read residential properties',
    Icon: VaultREIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VaultREIcon} iconColor="" />),
};
