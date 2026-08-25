// ElevenLabs AI Audio Platform automation node definition.
// Provides comprehensive audio generation, voice cloning, dubbing, and transcription integration.

import { memo, forwardRef, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Official ElevenLabs icon from https://elevenlabs.io/icon.svg
const ElevenLabsIcon: SvgIconComponent = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    ({ className, style, ...props }, ref) => {
        return (
            <svg
                ref={ref}
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 500 500"
                className={className}
                style={style}
                {...props}
            >
                <g clipPath="url(#clip0_470_2)">
                    <rect width="500" height="500" rx="100" fill="white"/>
                    <path d="M314 355H271V145H314V355Z" fill="black"/>
                    <path d="M229 355H186V145H229V355Z" fill="black"/>
                </g>
                <defs>
                    <clipPath id="clip0_470_2">
                        <rect width="500" height="500" fill="white"/>
                    </clipPath>
                </defs>
            </svg>
        );
    }
);
ElevenLabsIcon.displayName = 'ElevenLabsIcon';

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
