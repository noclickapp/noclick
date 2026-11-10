// Speechmatics catalog and canvas definition. Uses the official provider asset.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SpeechmaticsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/speechmatics.svg" dark="/icons/speechmatics-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
SpeechmaticsIcon.displayName = 'SpeechmaticsIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SpeechmaticsNode: NodeDefinition = {
    type: 'automation-speechmatics',
    label: 'Speechmatics',
    description: 'Transcribe, translate and summarize audio; manage jobs and export transcripts',
    category: 'ai',
    Icon: SpeechmaticsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SpeechmaticsIcon} iconColor="" />),
};
