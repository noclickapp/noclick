import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SwaggerHubIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/swaggerhub.svg" dark="/icons/swaggerhub-dark.svg" className={className} style={style} {...props} ref={ref} />
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
