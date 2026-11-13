import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';


const CommonRoomIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} ref={ref} light="/icons/common-room.svg" dark="/icons/common-room-dark.svg" className={className} style={style} />
    ),
);
CommonRoomIcon.displayName = 'CommonRoomIcon';

// Official favicon paths with transparent counters; provenance records each theme edit.
export const CommonRoomNode: NodeDefinition = {
    type: 'automation-common-room',
    label: 'Common Room',
    description: 'Contacts, organizations, segments, custom objects and activity triggers',
    category: 'crm-sales',
    Icon: CommonRoomIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CommonRoomIcon} iconColor="" />),
};
