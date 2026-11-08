import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AbyssaleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/abyssale.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AbyssaleNode: NodeDefinition = {
    type: 'automation-abyssale', label: 'Abyssale',
    category: 'media',
    description: 'Generate creative assets and manage Abyssale designs, projects and templates',
    Icon: AbyssaleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AbyssaleIcon} iconColor="" />),
};
