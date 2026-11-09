import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PlaudIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/plaud.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PlaudNode: NodeDefinition = {
    type: 'automation-plaud', category: 'meetings', label: 'Plaud',
    description: 'Read recordings, transcripts and summaries; manage device bindings and multipart uploads',
    keywords: ['recordings', 'transcription', 'meeting notes', 'PLAUD NOTE', 'NotePin'],
    Icon: PlaudIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PlaudIcon} iconColor="" />),
};
