import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SmartproxyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/smartproxy.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SmartproxyIcon.displayName = 'SmartproxyIcon';

// Official Decodo asset; Smartproxy is now Decodo.
export const SmartproxyNode: NodeDefinition = {
    type: 'automation-smartproxy',
    label: 'Smartproxy',
    keywords: ['Decodo', 'proxies', 'residential', 'traffic'],
    description: 'Manage proxy subusers, IP allowlists, endpoints and usage statistics',
    category: 'developer-tools',
    Icon: SmartproxyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SmartproxyIcon} iconColor="" />),
};
