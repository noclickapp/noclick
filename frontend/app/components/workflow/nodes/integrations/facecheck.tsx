import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FaceCheckIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/facecheck.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FaceCheckNode: NodeDefinition = {
    type: 'automation-facecheck', category: 'ai', label: 'FaceCheck',
    description: 'Upload search images, run searches, retrieve progress and results, and check credits',
    Icon: FaceCheckIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FaceCheckIcon} iconColor="" />),
};
