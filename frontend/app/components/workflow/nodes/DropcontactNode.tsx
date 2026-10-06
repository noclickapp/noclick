import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DropcontactIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/dropcontact.svg" alt="" className={className} style={style} {...props} />
);
DropcontactIcon.displayName = 'DropcontactIcon';
const DropcontactNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={DropcontactIcon} iconColor="" />;
export const DropcontactNode: NodeDefinition = {
    type: 'automation-dropcontact', label: 'Dropcontact',
    description: 'Dropcontact asynchronous B2B enrichment and credit metadata',
    Icon: DropcontactIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: DropcontactNodeComponent,
};
