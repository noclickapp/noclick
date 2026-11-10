import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties as BrandCSSProperties } from 'react';
// CircleCI brand mark supplied by Simple Icons.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <>
        <img src="/icons/circleci.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
        <img src="/icons/circleci-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
    </>
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
