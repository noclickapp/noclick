import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ChaserIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/chaser.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ChaserNode: NodeDefinition = {
    type: 'automation-chaser', category: 'finance-accounting', label: 'Chaser',
    description: 'Manage receivables, customers, invoices, contacts, notes and chasing',
    keywords: ['accounts receivable', 'invoice reminders', 'credit control'],
    Icon: ChaserIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ChaserIcon} iconColor="" />),
};
