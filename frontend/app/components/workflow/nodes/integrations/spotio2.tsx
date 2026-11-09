// Adds SPOTIO to the workflow canvas and integrations catalog.
// The icon is the publisher's unchanged favicon, documented by its sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const Spotio2Icon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/spotio2.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
Spotio2Icon.displayName = 'Spotio2Icon';

export const Spotio2Node: NodeDefinition = {
    type: 'automation-spotio2',
    label: 'SPOTIO',
    description: 'Search and manage field-sales records, activities, appointments, teams and territories',
    category: 'crm-sales',
    keywords: ['spotio', 'field sales', 'leads', 'appointments', 'territories'],
    Icon: Spotio2Icon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Spotio2Icon} iconColor="" />),
};
