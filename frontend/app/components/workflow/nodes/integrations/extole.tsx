import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ExtoleIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/extole.svg" alt="" className={className} style={style} {...props} />
);
ExtoleIcon.displayName = 'ExtoleIcon';
const ExtoleNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={ExtoleIcon} iconColor="" />;
export const ExtoleNode: NodeDefinition = {
    type: 'automation-extole',
    label: 'Extole',
    description: 'Participants, referral relationships, campaign drafts, reports and event receipts',
    category: 'marketing',
    Icon: ExtoleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ExtoleNodeComponent),
};
