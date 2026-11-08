import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AltovizIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/altoviz.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AltovizNode: NodeDefinition = {
    type: 'automation-altoviz', category: 'finance-accounting', label: 'Altoviz',
    description: 'Manage customers, products, invoices and quotes',
    Icon: AltovizIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AltovizIcon} iconColor="" />),
};
