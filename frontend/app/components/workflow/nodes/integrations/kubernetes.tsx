// Registers Kubernetes in the workflow canvas and integration catalog.
// This self-registering definition keeps its metadata and official icon together.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KubernetesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kubernetes.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const KubernetesNode: NodeDefinition = {
    type: 'automation-kubernetes', category: 'cloud-hosting', label: 'Kubernetes',
    description: 'Manage Kubernetes pods, deployments, services, ConfigMaps and jobs',
    Icon: KubernetesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KubernetesIcon} iconColor="" />),
};
