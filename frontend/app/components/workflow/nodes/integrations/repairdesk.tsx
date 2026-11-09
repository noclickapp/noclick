import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified vendor artwork from https://www.repairdesk.co/
const RepairDeskIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/repairdesk-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);
export const RepairDeskNode: NodeDefinition = {
    type: 'automation-repairdesk', label: 'RepairDesk', category: 'industry',
    description: 'Purchase orders, goods received notes, status metadata and change triggers',
    Icon: RepairDeskIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RepairDeskIcon} iconColor="" />),
};
