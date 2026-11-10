import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PlaudIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/plaud.svg" dark="/icons/plaud-dark.svg" className={className} style={style} />
);

export const PlaudNode: NodeDefinition = {
    type: 'automation-plaud', category: 'meetings', label: 'Plaud',
    description: 'Trigger on new or updated recordings; read transcripts and summaries, manage devices and uploads',
    keywords: ['recordings', 'transcription', 'meeting notes', 'PLAUD NOTE', 'NotePin'],
    Icon: PlaudIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PlaudIcon} iconColor="" />),
};
