import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CodacyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/codacy.svg" dark="/icons/codacy-dark.svg" className={className} style={style} {...props} ref={ref} />
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
