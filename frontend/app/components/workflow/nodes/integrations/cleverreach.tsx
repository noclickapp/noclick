import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CleverreachIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cleverreach.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CleverreachNode: NodeDefinition = {
    type: 'automation-cleverreach', label: 'CleverReach',
    description: 'Manage receiver lists, subscribers, tags, mailings and reports',
    Icon: CleverreachIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CleverreachIcon} iconColor="" />),
};
