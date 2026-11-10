import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PocketSmithIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/pocketsmith.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PocketSmithNode: NodeDefinition = {
    type: 'automation-pocketsmith', category: 'finance-accounting', label: 'PocketSmith',
    description: 'Read accounts and budgets; create, update and organise transactions and categories',
    Icon: PocketSmithIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PocketSmithIcon} iconColor="" />),
};
