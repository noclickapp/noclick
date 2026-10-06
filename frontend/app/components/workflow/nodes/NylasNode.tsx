import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const NylasIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/nylas.svg" alt="" className={className}
            style={{ ...style, objectFit: 'contain' }} {...props} />
    )
);
NylasIcon.displayName = 'NylasIcon';

export const NylasNode: NodeDefinition = {
    type: 'automation-nylas',
    label: 'Nylas',
    description: 'Connected mail, calendar and contact metadata; unsent drafts and ordinary contact/calendar operations',
    Icon: NylasIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NylasIcon} iconColor="" />),
};
