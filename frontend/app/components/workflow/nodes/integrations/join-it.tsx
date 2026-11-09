import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const JoinItIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/join-it.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
JoinItIcon.displayName = 'JoinItIcon';

export const JoinItNode: NodeDefinition = {
    type: 'automation-join-it',
    label: 'Join It',
    category: 'nonprofit',
    description: 'Manage memberships, verify membership status and record offline payments',
    keywords: ['membership', 'members', 'nonprofit', 'association', 'joinit'],
    Icon: JoinItIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JoinItIcon} iconColor="" />),
};
