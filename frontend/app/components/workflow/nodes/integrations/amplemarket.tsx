import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const AmplemarketIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/amplemarket.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AmplemarketIcon.displayName = 'AmplemarketIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const AmplemarketNode: NodeDefinition = {
    type: 'automation-amplemarket',
    label: 'Amplemarket',
    description: 'Enrich prospects, manage contacts, sequences, lead lists and calls',
    category: 'crm-sales',
    Icon: AmplemarketIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AmplemarketIcon} iconColor="" />),
};
