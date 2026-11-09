// Loopy Loyalty's native definition makes its stamp-card operations discoverable.
// The official publisher icon is reviewed in the adjacent provenance sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const LoopyLoyaltyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/loopy-loyalty.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
LoopyLoyaltyIcon.displayName = 'LoopyLoyaltyIcon';

export const LoopyLoyaltyNode: NodeDefinition = {
    type: 'automation-loopy-loyalty',
    label: 'Loopy Loyalty',
    description: 'Manage loyalty cards, stamps, rewards and customer messages',
    category: 'marketing',
    keywords: ['loyalty', 'digital stamp cards', 'rewards', 'Apple Wallet', 'Google Wallet'],
    Icon: LoopyLoyaltyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LoopyLoyaltyIcon} iconColor="" />),
};
