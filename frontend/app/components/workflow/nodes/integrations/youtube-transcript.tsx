// Registers YouTube Transcript in the workflow palette and integration catalog.
// Uses the provider icon to identify transcript automation on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const YoutubeTranscriptIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/youtube-transcript.svg" dark="/icons/youtube-transcript-dark.svg" className={className} style={style} />
);

export const YoutubeTranscriptNode: NodeDefinition = {
    type: 'automation-youtube-transcript', category: 'content-research', label: 'YouTube Transcript',
    description: 'Transcribe and translate YouTube videos, manage transcripts and organize folders, and start workflows when a transcript is ready',
    keywords: ['YouTubeTranscript.dev', 'captions', 'subtitles', 'transcription', 'youtube_transcript'],
    Icon: YoutubeTranscriptIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={YoutubeTranscriptIcon} iconColor="" />),
};
