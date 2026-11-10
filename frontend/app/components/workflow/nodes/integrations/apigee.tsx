import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const ApigeeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/apigee.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);
export const ApigeeNode: NodeDefinition = {
    type: 'automation-apigee', category: 'developer-tools', label: 'Registry API',
    description: 'Manage API descriptions, versions, specifications and deployments; watch API updates',
    keywords: ['Apigee', 'Google Cloud', 'API registry'],
    Icon: ApigeeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApigeeIcon} iconColor="" />),
};
