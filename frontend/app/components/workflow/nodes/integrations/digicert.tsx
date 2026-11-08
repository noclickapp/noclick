import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DigicertIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/digicert.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DigicertIcon.displayName = 'DigicertIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const DigicertNode: NodeDefinition = {
    type: 'automation-digicert',
    label: 'DigiCert',
    description: 'Content Trust Manager validations, credentials and audit logs',
    category: 'developer-tools',
    Icon: DigicertIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DigicertIcon} iconColor="" />),
};
