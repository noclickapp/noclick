import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const StreamtimeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/streamtime.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/streamtime-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
StreamtimeIcon.displayName = 'StreamtimeIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const StreamtimeNode: NodeDefinition = {
    type: 'automation-streamtime',
    label: 'Streamtime',
    description: 'Jobs, companies, contacts, time entries and search',
    category: 'productivity',
    Icon: StreamtimeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StreamtimeIcon} iconColor="" />),
};
