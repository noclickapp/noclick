import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SpotifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/spotify.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SpotifyNode: NodeDefinition = {
    type: 'automation-spotify', category: 'media', label: 'Spotify',
    description: 'Manage playlists, library and playback, and watch played tracks',
    keywords: ['music', 'songs', 'playlist', 'listening', 'queue'],
    Icon: SpotifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SpotifyIcon} iconColor="" />),
};
