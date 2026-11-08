import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SymplaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sympla.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain', backgroundColor: '#0097ff', borderRadius: 6, padding: 4 } as CSSProperties} />
);

export const SymplaNode: NodeDefinition = {
    type: 'automation-sympla', label: 'Sympla',
    description: 'Read events, orders, participants and presentations, and check in tickets',
    Icon: SymplaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SymplaIcon} iconColor="" />),
};
