import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoodyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/goody.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GoodyNode: NodeDefinition = {
    type: 'automation-goody', label: 'Goody',
    description: 'Send gifts, estimate costs, and manage Goody orders and catalogs',
    Icon: GoodyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoodyIcon} iconColor="" />),
};
