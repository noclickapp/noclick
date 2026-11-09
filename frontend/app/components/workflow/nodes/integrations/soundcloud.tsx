import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SoundcloudIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/soundcloud.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain', backgroundColor: '#FF5500' } as CSSProperties} />
);

export const SoundcloudNode: NodeDefinition = {
    type: 'automation-soundcloud', category: 'social-media', label: 'SoundCloud',
    description: 'Manage SoundCloud tracks, playlists, follows, likes and reposts',
    Icon: SoundcloudIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SoundcloudIcon} iconColor="" />),
};
