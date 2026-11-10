import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const HiveIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/hive.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HiveIcon.displayName = 'HiveIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const HiveNode: NodeDefinition = {
    type: 'automation-hive',
    label: 'Hive',
    description: 'Automate Hive actions, projects, comments and labels',
    category: 'productivity',
    Icon: HiveIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HiveIcon} iconColor="" />),
};
