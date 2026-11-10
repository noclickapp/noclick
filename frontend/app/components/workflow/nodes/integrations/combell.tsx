import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CombellIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/combell.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CombellIcon.displayName = 'CombellIcon';

// Official publisher asset; provenance is recorded beside the icon.
export const CombellNode: NodeDefinition = {
    type: 'automation-combell',
    label: 'Combell',
    description: 'Reseller accounts, DNS, domains, hosting and mailboxes',
    category: 'cloud-hosting',
    Icon: CombellIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CombellIcon} iconColor="" />),
};
