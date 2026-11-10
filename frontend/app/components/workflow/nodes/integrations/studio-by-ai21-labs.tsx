import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const StudioByAI21LabsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            ref={ref}
            src="/icons/studio-by-ai21-labs.svg"
            alt=""
            className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }}
            {...props}
        />
        <img
            src="/icons/studio-by-ai21-labs-dark.svg"
            alt=""
            className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }}
            {...props}
        />
    </>
));
StudioByAI21LabsIcon.displayName = 'StudioByAI21LabsIcon';

// Exact publisher asset; provenance is recorded beside the image.
export const StudioByAI21LabsNode: NodeDefinition = {
    type: 'automation-studio-by-ai21-labs',
    label: 'Studio By AI21 Labs',
    description:
        'Manage library files, generate Jamba chat completions and run Maestro',
    category: 'ai',
    keywords: ['AI21', 'Jamba', 'Maestro', 'AI21 Studio'],
    Icon: StudioByAI21LabsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={StudioByAI21LabsIcon} iconColor="" />
    )),
};
