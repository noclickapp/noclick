import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OrshotIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/orshot.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const OrshotNode: NodeDefinition = {
    type: 'automation-orshot', label: 'Orshot',
    category: 'media',
    description: 'Render templates and manage render jobs, folders and brand assets',
    Icon: OrshotIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OrshotIcon} iconColor="" />),
};
