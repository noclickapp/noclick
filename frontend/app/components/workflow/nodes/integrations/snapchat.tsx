// Registers Snapchat in the workflow palette and social media catalog.
// Uses the official Snapchat icon to identify its Conversions API actions.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SnapchatIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/snapchat.svg" dark="/icons/snapchat-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
SnapchatIcon.displayName = 'SnapchatIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const SnapchatNode: NodeDefinition = {
    type: 'automation-snapchat',
    label: 'Snapchat',
    description: 'Send website conversions and read asset test diagnostics',
    category: 'social-media',
    Icon: SnapchatIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SnapchatIcon} iconColor="" />),
};
