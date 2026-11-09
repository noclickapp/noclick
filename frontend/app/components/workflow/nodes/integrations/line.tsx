import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LineIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/line.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LineNode: NodeDefinition = {
    type: 'automation-line', category: 'communication', label: 'LINE',
    description: 'Send messages and manage LINE Official Account profiles, members and rich menus',
    Icon: LineIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LineIcon} iconColor="" />),
};
