import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SystemeioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/systemeio.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SystemeioNode: NodeDefinition = {
    type: 'automation-systemeio', category: 'marketing', label: 'systeme.io',
    description: 'Manage contacts, tags, campaigns, courses and enrollments',
    Icon: SystemeioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SystemeioIcon} iconColor="" />),
};
