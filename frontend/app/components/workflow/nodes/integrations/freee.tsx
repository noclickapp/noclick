import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FreeeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/freee.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FreeeNode: NodeDefinition = {
    type: 'automation-freee', label: 'Freee',
    keywords: ['accounting', 'bookkeeping', '会計', 'freee会計'],
    description: 'Automate accounting deals, partners, invoices, tags and items',
    Icon: FreeeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FreeeIcon} iconColor="" />),
};
