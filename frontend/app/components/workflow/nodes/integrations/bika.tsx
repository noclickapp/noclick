import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BikaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bika.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BikaNode: NodeDefinition = {
    type: 'automation-bika', category: 'productivity', label: 'Bika',
    description: 'Read workspaces and create, retrieve, update and delete database records',
    Icon: BikaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BikaIcon} iconColor="" />),
};
