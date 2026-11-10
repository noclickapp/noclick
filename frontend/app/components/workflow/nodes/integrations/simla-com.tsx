import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SimlaComIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/simla-com.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SimlaComNode: NodeDefinition = {
    type: 'automation-simla-com', category: 'crm-sales', label: 'Simla Com',
    description: 'Automate customer conversations, dialogs, messages and bot profiles',
    Icon: SimlaComIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SimlaComIcon} iconColor="" />),
};
