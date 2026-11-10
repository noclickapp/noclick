import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.docker.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <>
        <img src="/icons/docker-hub-brand-vector.svg" alt="" aria-hidden="true"
            className={`${className || ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/docker-hub-brand-vector-dark.svg" alt="" aria-hidden="true"
            className={`${className || ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} />
    </>
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DockerHubNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const DockerHubNode: NodeDefinition = {
    type: 'automation-docker-hub',
    category: 'developer-tools',
    label: 'Docker Hub',
    description:
        'Manage Docker Hub repositories and teams; trigger on repository changes, image pushes, and audit events',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(DockerHubNodeComponent),
};
