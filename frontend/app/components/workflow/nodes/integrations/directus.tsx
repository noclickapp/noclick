import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DirectusIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/directus.svg"
        alt=""
        className={className}
        {...props}
    />
));
DirectusIcon.displayName = 'DirectusIcon';

export const DirectusNode: NodeDefinition = {
    type: 'automation-directus',
    label: 'Directus',
    description: 'Manage content, collections, files, and folders in Directus',
    Icon: DirectusIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={DirectusIcon} iconColor="" />
    )),
};
