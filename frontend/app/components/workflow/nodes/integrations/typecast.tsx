import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TypecastIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/typecast.svg" dark="/icons/typecast-dark.svg" className={className} style={style} />
);

export const TypecastNode: NodeDefinition = {
    type: 'automation-typecast', category: 'ai', label: 'Typecast',
    description: 'Generate speech, compose voiceovers, discover voices and manage custom voices',
    keywords: ['text to speech', 'tts', 'voiceover', 'audio'],
    Icon: TypecastIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TypecastIcon} iconColor="" />),
};
