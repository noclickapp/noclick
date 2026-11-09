import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SwaggerHubIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/swaggerhub.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SwaggerHubIcon.displayName = 'SwaggerHubIcon';

// Publisher asset; provenance is recorded beside the image.
export const SwaggerHubNode: NodeDefinition = {
    type: 'automation-swaggerhub',
    label: 'SwaggerHub',
    keywords: ['Swagger', 'OpenAPI', 'Swagger Studio', 'API Hub'],
    description: 'Manage API versions, lifecycle, visibility, domains and projects',
    category: 'developer-tools',
    Icon: SwaggerHubIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SwaggerHubIcon} iconColor="" />),
};
