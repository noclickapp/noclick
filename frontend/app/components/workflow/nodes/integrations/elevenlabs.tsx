// ElevenLabs AI Audio Platform automation node definition.
// Provides comprehensive audio generation, voice cloning, dubbing, and transcription integration.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Official ElevenLabs icon from https://elevenlabs.io/icon.svg
const ElevenLabsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/elevenlabs.svg" dark="/icons/elevenlabs-dark.svg" className={className} style={style} />
);

const ElevenLabsNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={ElevenLabsIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const ElevenLabsNode: NodeDefinition = {
    type: 'automation-elevenlabs',
    label: 'ElevenLabs',
    description: 'ElevenLabs automation',
    Icon: ElevenLabsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ElevenLabsNodeComponent),
};
