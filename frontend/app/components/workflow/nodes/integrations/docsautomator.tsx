import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DocsautomatorIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/docsautomator.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DocsautomatorIcon.displayName = 'DocsautomatorIcon';

// Official publisher favicon; provenance is recorded beside the image.
export const DocsautomatorNode: NodeDefinition = {
    type: 'automation-docsautomator',
    label: 'DocsAutomator',
    category: 'documents',
    description: 'Generate documents, manage automations and track signing',
    Icon: DocsautomatorIcon,
    keywords: ['Docsautomator', 'PDF', 'document generation', 'e-signature'],
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DocsautomatorIcon} iconColor="" />),
};
