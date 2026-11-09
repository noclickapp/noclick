import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DigitalOceanIcon = ({ className }: { className?: string }) => (
    <img src="/icons/digitalocean.svg" alt="" aria-hidden="true" className={className} />
);

export const DigitalOceanNode: NodeDefinition = {
    type: 'automation-digitalocean',
    label: 'DigitalOcean',
    description: 'Manage cloud resources and monitor new alerts in DigitalOcean',
    category: 'cloud-hosting',
    Icon: DigitalOceanIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DigitalOceanIcon} iconColor="" />),
};
