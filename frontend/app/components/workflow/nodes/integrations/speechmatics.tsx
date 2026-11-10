// Speechmatics catalog and canvas definition. Uses the official provider asset.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SpeechmaticsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/speechmatics.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/speechmatics-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
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
