import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const OneNoteIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/microsoft-onenote.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
OneNoteIcon.displayName = 'OneNoteIcon';

const OneNoteNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OneNoteIcon} iconColor="" />
);

export const OneNoteNode: NodeDefinition = {
    type: 'automation-microsoft-onenote',
    label: 'OneNote',
    description: 'Microsoft OneNote notebooks, pages, and page change triggers',
    category: 'microsoft',
    Icon: OneNoteIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(OneNoteNodeComponent),
};
