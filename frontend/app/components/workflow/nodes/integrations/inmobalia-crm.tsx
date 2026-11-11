import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InmobaliaCRMIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/inmobalia-crm.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const InmobaliaCRMNode: NodeDefinition = {
    type: 'automation-inmobalia-crm', category: 'crm-sales', label: 'Inmobalia CRM',
    description: 'Manage contacts, web leads, properties and activities; watch CRM changes',
    keywords: ['real estate', 'property', 'Inmoba', 'leads', 'CRM'],
    Icon: InmobaliaCRMIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InmobaliaCRMIcon} iconColor="" />),
};
