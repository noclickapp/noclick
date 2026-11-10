import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FrameIoV4Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/frame-io-v4.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FrameIoV4Node: NodeDefinition = {
    type: 'automation-frame-io-v4', category: 'media', label: 'Frame.io V4',
    description: 'Manage projects, folders, files, comments and review shares',
    Icon: FrameIoV4Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FrameIoV4Icon} iconColor="" />),
};
