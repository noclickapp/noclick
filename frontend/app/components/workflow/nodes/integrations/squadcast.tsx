// SquadCast incident response operations use the standard automation renderer.
// The publisher icon is kept locally with its source and byte hash beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const SquadCastIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/squadcast.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SquadCastIcon.displayName = 'SquadCastIcon';

export const SquadCastNode: NodeDefinition = {
    type: 'automation-squadcast',
    label: 'SquadCast',
    description: 'Manage incidents, notes, services, teams, users and on-call schedules',
    category: 'monitoring',
    keywords: ['incident response', 'on call', 'alerts', 'squadcast'],
    Icon: SquadCastIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SquadCastIcon} iconColor="" />),
};
