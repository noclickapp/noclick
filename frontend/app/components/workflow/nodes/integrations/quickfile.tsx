import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const QuickFileIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/quickfile.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const QuickFileNode: NodeDefinition = {
    type: 'automation-quickfile', category: 'finance-accounting', label: 'QuickFile',
    description: 'Manage clients, suppliers, invoices, payments and purchases; watch for new clients and suppliers.',
    keywords: ['accounting', 'bookkeeping', 'invoices', 'QuickFile'],
    Icon: QuickFileIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={QuickFileIcon} iconColor="" />),
};
