// Registers Snapchat in the workflow palette and social media catalog.
// Uses the official Snapchat icon to identify its Conversions API actions.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SnapchatIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/snapchat.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/snapchat-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
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
