import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://raw.githubusercontent.com/Dokploy/dokploy/v0.30.8/apps/dokploy/public/logo.svg
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/dokploy.svg" dark="/icons/dokploy-dark.svg" className={className} style={style} />
);

export const DokployNode: NodeDefinition = {
    type: 'automation-dokploy',
    label: 'Dokploy',
    description: 'Project, environment and service status; existing deployment metadata',
    category: 'cloud-hosting',
    keywords: ['project', 'environment', 'application', 'compose', 'deployment status', 'self hosted'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
