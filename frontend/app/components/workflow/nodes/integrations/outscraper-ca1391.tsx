import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const OutscraperIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/outscraper-ca1391.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
OutscraperIcon.displayName = 'OutscraperIcon';

export const OutscraperNode: NodeDefinition = {
    type: 'automation-outscraper-ca1391',
    label: 'Outscraper',
    description: 'Scrape places and reviews, enrich contacts, verify emails and receive signed job completion events',
    category: 'content-research',
    keywords: ['Google Maps', 'leads', 'scraping', 'email verification'],
    Icon: OutscraperIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OutscraperIcon} iconColor="" />),
};
