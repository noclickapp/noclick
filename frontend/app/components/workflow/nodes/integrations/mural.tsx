import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const MuralIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            ref={ref}
            src="/icons/mural.svg"
            alt=""
            className={`${className ?? ''} dark:hidden`}
            style={style}
            {...props}
        />
        <img
            src="/icons/mural-dark.svg"
            alt=""
            className={`${className ?? ''} hidden dark:block`}
            style={style}
            {...props}
        />
    </>
));
MuralIcon.displayName = 'MuralIcon';

const MuralNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={MuralIcon} iconColor="" />
);

export const MuralNode: NodeDefinition = {
    type: 'automation-mural',
    label: 'Mural',
    description: 'Mural workspaces, rooms, murals, templates and widgets',
    category: 'productivity',
    Icon: MuralIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MuralNodeComponent),
};
