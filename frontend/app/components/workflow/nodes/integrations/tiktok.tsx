// TikTok automation node definition.
// Provides workflow integration for TikTok content posting, user info, video reading, and Research API.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

// TikTok's note from its own site, with its black top layer for light mode; source and edits are in the provenance files.
// Rendered inline so width/height/style/className pass-through work correctly.
const TikTokIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/tiktok.svg" dark="/icons/tiktok-dark.svg" className={className} style={style} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 58 };

const TikTokNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={TikTokIcon as any}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const TikTokNode: NodeDefinition = {
    type: 'automation-tiktok',
    label: 'TikTok',
    description: 'TikTok automation',
    Icon: TikTokIcon as any,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(TikTokNodeComponent),
};
