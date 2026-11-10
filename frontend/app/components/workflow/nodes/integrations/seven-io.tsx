// Seven Io exposes messaging and address-book automation on the canvas.
// This definition supplies its official brand icon and catalog label.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SevenIoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/seven-io.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SevenIoIcon.displayName = 'SevenIoIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SevenIoNode: NodeDefinition = {
    type: 'automation-seven-io',
    label: 'Seven Io',
    description: 'SMS, contacts, groups, journals and number lookup',
    category: 'communication',
    Icon: SevenIoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SevenIoIcon} iconColor="" />),
};
