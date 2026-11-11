import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 64 };

// Semrush Icon Component - Official Semrush Logo
const SemrushIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/semrush.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SemrushNode: NodeDefinition = {
    type: 'automation-semrush',
    label: 'Semrush',
    description: 'Semrush automation',
    Icon: SemrushIcon as any,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={SemrushIcon as any} iconColor="" />
    )),
};
