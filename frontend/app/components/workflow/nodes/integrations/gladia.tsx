// Discoverable canvas definition for the Gladia integration.
// The shared automation node renders the generated configuration schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GladiaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gladia.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GladiaNode: NodeDefinition = {
    type: 'automation-gladia', label: 'Gladia',
    description: 'Upload media, transcribe recordings and manage live speech sessions',
    category: 'ai',
    keywords: ['speech to text', 'audio', 'transcription', 'diarization', 'subtitles'],
    Icon: GladiaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GladiaIcon} iconColor="" />),
};
