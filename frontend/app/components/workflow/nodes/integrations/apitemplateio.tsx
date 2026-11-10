import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const APITemplateIOIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/apitemplateio.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
APITemplateIOIcon.displayName = 'APITemplateIOIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const APITemplateIONode: NodeDefinition = {
    type: 'automation-apitemplateio',
    label: 'APITemplate.io',
    description: 'Generate PDFs and images, manage templates and merge PDFs',
    category: 'documents',
    Icon: APITemplateIOIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={APITemplateIOIcon} iconColor="" />),
};
