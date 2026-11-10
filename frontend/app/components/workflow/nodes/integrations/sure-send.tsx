import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SureSendIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sure-send.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SureSendNode: NodeDefinition = {
    type: 'automation-sure-send', category: 'crm-sales', label: 'Sure Send',
    description: 'Manage CRM contacts, notes, tasks, appointments, automations and messages',
    Icon: SureSendIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SureSendIcon} iconColor="" />),
};
