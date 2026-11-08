import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VimeoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/vimeo.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const VimeoNode: NodeDefinition = {
    type: 'automation-vimeo', label: 'Vimeo',
    description: 'Manage videos, comments, likes and folders',
    Icon: VimeoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VimeoIcon} iconColor="" />),
};
