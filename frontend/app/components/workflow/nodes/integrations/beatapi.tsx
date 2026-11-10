import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const BeatapiIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/beatapi.png" dark="/icons/beatapi-dark.png" className={className} style={style} {...props} ref={ref} />
));
BeatapiIcon.displayName = 'BeatapiIcon';

export const BeatapiNode: NodeDefinition = {
    type: 'automation-beatapi',
    label: 'BeatAPI',
    description:
        'Generate media, manage video workflows, inspect usage and configure webhooks',
    category: 'ai',
    Icon: BeatapiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={BeatapiIcon} iconColor="" />
    )),
};
