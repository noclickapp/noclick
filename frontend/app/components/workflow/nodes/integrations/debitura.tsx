import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DebituraIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/debitura.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const DebituraNode: NodeDefinition = {
    type: 'automation-debitura', category: 'finance-accounting', label: 'Debitura',
    description: 'Create debt collection cases, track payments and manage creditor divisions',
    Icon: DebituraIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DebituraIcon} iconColor="" />),
};
