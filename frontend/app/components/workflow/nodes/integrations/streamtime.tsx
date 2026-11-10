import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const StreamtimeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/streamtime.svg" dark="/icons/streamtime-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
StreamtimeIcon.displayName = 'StreamtimeIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const StreamtimeNode: NodeDefinition = {
    type: 'automation-streamtime',
    label: 'Streamtime',
    description: 'Jobs, companies, contacts, time entries and search',
    category: 'productivity',
    Icon: StreamtimeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StreamtimeIcon} iconColor="" />),
};
