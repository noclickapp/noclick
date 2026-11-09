import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const NutrientIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/nutrient-document-web-services-api.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
NutrientIcon.displayName = 'NutrientIcon';
export const NutrientDocumentWebServicesApiNode: NodeDefinition = {
    type: 'automation-nutrient-document-web-services-api',
    label: 'Nutrient Document Web Services API',
    description: 'Parse, extract, classify and split documents; manage processing runs and reusable processors.',
    category: 'documents',
    Icon: NutrientIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NutrientIcon} iconColor="" />),
};
