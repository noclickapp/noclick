import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SpotifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/spotify-mark.svg" className={className} style={style} />
);

export const SpotifyNode: NodeDefinition = {
    type: 'automation-spotify', category: 'media', label: 'Spotify',
    description: 'Manage playlists, library and playback, and watch played tracks',
    keywords: ['music', 'songs', 'playlist', 'listening', 'queue'],
    Icon: SpotifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SpotifyIcon} iconColor="" />),
};
