import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// CircleCI brand mark supplied by Simple Icons.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/circleci.svg" dark="/icons/circleci-dark.svg" className={className} style={style} />
);

const CircleCINodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const CircleCINode: NodeDefinition = {
    type: 'automation-circleci',
    label: 'CircleCI',
    description: 'Pipelines, workflows, jobs, projects, contexts, and insights',
    category: 'developer-tools',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: CircleCINodeComponent,
};
