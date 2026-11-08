import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CodacyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/codacy.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CodacyIcon.displayName = 'CodacyIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const CodacyNode: NodeDefinition = {
    type: 'automation-codacy',
    label: 'Codacy',
    description: 'Automate code analysis, repositories, pull requests and issues',
    category: 'developer-tools',
    Icon: CodacyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CodacyIcon} iconColor="" />),
};
