// ElevenLabs AI Audio Platform automation node definition.
// Provides comprehensive audio generation, voice cloning, dubbing, and transcription integration.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Official ElevenLabs icon from https://elevenlabs.io/icon.svg
const ElevenLabsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/elevenlabs.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/elevenlabs-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
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
