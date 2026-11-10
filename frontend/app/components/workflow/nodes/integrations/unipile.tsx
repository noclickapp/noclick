import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const UnipileIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/unipile.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
UnipileIcon.displayName = 'UnipileIcon';

// Official publisher icon; provenance is recorded beside the image.
export const UnipileNode: NodeDefinition = {
    type: 'automation-unipile',
    label: 'Unipile',
    description: 'Messages, email, profiles and network invitations',
    category: 'communication',
    Icon: UnipileIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UnipileIcon} iconColor="" />),
};
