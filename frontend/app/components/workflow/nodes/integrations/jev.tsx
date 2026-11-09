// Defines the discoverable Jev integration for the canvas and catalog.
// Uses the publisher's TypeSafe icon because Jev is its System One model.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const JevIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/jev.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
JevIcon.displayName = 'JevIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const JevNode: NodeDefinition = {
    type: 'automation-jev',
    label: 'Jev',
    description: 'Typed decisions, classification, scoring and image localization',
    category: 'ai',
    Icon: JevIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JevIcon} iconColor="" />),
};
