import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZenoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zeno.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const ZenoNode: NodeDefinition = {
    type: 'automation-zeno', category: 'media', label: 'Aggregators API Service',
    description: 'Manage Zeno podcasts, publish episodes, process audio, retrieve transcripts and monitor new videos',
    keywords: ['Zeno', 'Zeno.fm', 'Podcast Bot', 'radio', 'podcast'],
    Icon: ZenoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZenoIcon} iconColor="" />),
};
