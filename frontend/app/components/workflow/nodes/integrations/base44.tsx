// Base44's Apps API provides records, app metadata, and app user automation.
// This definition makes the self-registering integration available in both palettes.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const Base44Icon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/base44.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
Base44Icon.displayName = 'Base44Icon';

export const Base44Node: NodeDefinition = {
    type: 'automation-base44',
    label: 'Base44',
    description: 'Automate app records, schemas, metadata, and users',
    category: 'developer-tools',
    keywords: ['database', 'entities', 'records', 'apps'],
    Icon: Base44Icon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Base44Icon} iconColor="" />),
};
