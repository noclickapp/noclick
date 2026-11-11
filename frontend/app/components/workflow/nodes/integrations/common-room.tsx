import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CommonRoomIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img {...props} ref={ref} src="/icons/common-room.svg" alt="" className={`${className || ''} dark:hidden `} style={style} />
            <img {...props} src="/icons/common-room-dark.svg" alt="" className={`${className || ''} hidden dark:block `} style={style} />
        </>
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
