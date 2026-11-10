import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ImagerouterIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/imagerouter.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ImagerouterNode: NodeDefinition = {
    type: 'automation-imagerouter', category: 'ai', label: 'ImageRouter',
    description: 'Generate images, videos and text; discover models and monitor credit usage',
    Icon: ImagerouterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ImagerouterIcon} iconColor="" />),
};
