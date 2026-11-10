// Simplesat canvas definition and official provider icon.
// Self discovery makes this integration available to the workflow palettes.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SimplesatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/simplesat.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SimplesatNode: NodeDefinition = {
    type: 'automation-simplesat', category: 'support', label: 'Simplesat',
    description: 'Manage customers, feedback, surveys and team members',
    Icon: SimplesatIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SimplesatIcon} iconColor="" />),
};
