import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ClioIcon: SvgIconComponent = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/clio-brand-vector.svg" alt="" className={className} style={style} {...props} />
    ),
);
ClioIcon.displayName = 'ClioIcon';
const ClioNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ClioIcon} iconColor="#0B5CAD" />
);
export const ClioNode: NodeDefinition = {
    type: 'automation-clio',
    label: 'Clio',
    description: 'Clio Manage matters, contacts, documents, activities, and billing',
    Icon: ClioIcon,
    iconColor: '#0B5CAD',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ClioNodeComponent),
};
