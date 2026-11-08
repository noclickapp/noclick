/** Registers Alchemy in the workflow palette and integrations directory.
 * Uses the official brand icon for app and allowlist management operations. */
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AlchemyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/alchemy.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AlchemyIcon.displayName = 'AlchemyIcon';

export const AlchemyNode: NodeDefinition = {
    type: 'automation-alchemy',
    label: 'Alchemy',
    description: 'Manage blockchain apps, networks and access allowlists',
    category: 'developer-tools',
    keywords: ['web3', 'blockchain', 'ethereum', 'app management'],
    Icon: AlchemyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 56 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AlchemyIcon} iconColor="" />),
};
