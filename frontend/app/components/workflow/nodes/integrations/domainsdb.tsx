import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DomainsdbIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/domainsdb.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DomainsdbIcon.displayName = 'DomainsdbIcon';

// Official symbol paths, cropped from the provider logo; provenance is beside the SVG.
export const DomainsdbNode: NodeDefinition = {
    type: 'automation-domainsdb',
    label: 'Domains-Index API',
    description: 'Search domains, inspect DNS records and watch domain updates',
    category: 'developer-tools',
    keywords: ['domainsdb', 'DNS', 'domain research'],
    Icon: DomainsdbIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DomainsdbIcon} iconColor="" />),
};
