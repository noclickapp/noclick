import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DebounceIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/debounce.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DebounceIcon.displayName = 'DebounceIcon';

// Official publisher icon; provenance is recorded beside the image.
export const DebounceNode: NodeDefinition = {
    type: 'automation-debounce',
    label: 'Debounce',
    category: 'marketing',
    description: 'Email validation, bulk lists, enrichment and account credits',
    Icon: DebounceIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DebounceIcon} iconColor="" />),
};
