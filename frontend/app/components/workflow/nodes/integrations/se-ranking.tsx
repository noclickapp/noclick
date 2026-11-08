import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const SERankingIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/se-ranking.svg" alt="" className={className} style={style} {...props} />,
);
SERankingIcon.displayName = 'SERankingIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={SERankingIcon} iconColor="" />;
export const SERankingNode: NodeDefinition = {
    type: 'automation-se-ranking', category: 'marketing', label: 'SE Ranking', description: 'Project-bound search engines, keywords, rankings, groups, competitors and existing audit metadata.',
    Icon: SERankingIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 48 }, component: Component,
};
