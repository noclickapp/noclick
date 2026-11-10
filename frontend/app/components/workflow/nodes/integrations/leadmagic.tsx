import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeadmagicIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/leadmagic.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LeadmagicNode: NodeDefinition = {
    type: 'automation-leadmagic', category: 'crm-sales', label: 'LeadMagic',
    description: 'Enrich people and companies, validate email and manage batches',
    Icon: LeadmagicIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeadmagicIcon} iconColor="" />),
};
