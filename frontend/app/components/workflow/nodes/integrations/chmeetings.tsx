import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ChmeetingsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/chmeetings.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ChmeetingsNode: NodeDefinition = {
    type: 'automation-chmeetings', label: 'Chmeetings',
    description: 'Manage people, groups, memberships and notes; read families and organizations',
    Icon: ChmeetingsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ChmeetingsIcon} iconColor="" />),
};
