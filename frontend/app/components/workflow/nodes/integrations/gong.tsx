import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GongIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/gong-brand.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GongIcon.displayName = 'GongIcon';

const GongNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={GongIcon} iconColor="" />
);

export const GongNode: NodeDefinition = {
    type: 'automation-gong',
    label: 'Gong',
    description: 'Gong calls, transcripts, users, workspaces, CRM and Engage automation',
    Icon: GongIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GongNodeComponent),
};
