import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const AnakinIoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/anakin-io.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AnakinIoIcon.displayName = 'AnakinIoIcon';

// Exact publisher asset; provenance is recorded beside the image.
export const AnakinIoNode: NodeDefinition = {
    type: 'automation-anakin-io',
    label: 'Anakin Io',
    description: 'Scrape, search, crawl, run Wire actions and monitor websites',
    category: 'content-research',
    Icon: AnakinIoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AnakinIoIcon} iconColor="" />),
};
