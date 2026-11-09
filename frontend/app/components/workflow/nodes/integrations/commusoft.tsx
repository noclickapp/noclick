// Commusoft's self-registering workflow definition. The official project icon
// identifies the service in the canvas and integrations catalogue.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CommusoftIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/commusoft.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CommusoftNode: NodeDefinition = {
    type: 'automation-commusoft', category: 'industry', label: 'Commusoft',
    description: 'Manage customers, contacts, assets, opportunities, jobs and appointments',
    Icon: CommusoftIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CommusoftIcon} iconColor="" />),
};
