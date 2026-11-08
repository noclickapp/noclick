import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AhaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/aha.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AhaNode: NodeDefinition = {
    type: 'automation-aha', label: 'Aha!',
    description: 'Automate workspaces, releases, features, epics, ideas, requirements and notes',
    Icon: AhaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AhaIcon} iconColor="" />),
};
