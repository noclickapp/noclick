import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AnakinIoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/anakin-io.png" dark="/icons/anakin-io-dark.png" className={className} style={style} {...props} ref={ref} />
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
