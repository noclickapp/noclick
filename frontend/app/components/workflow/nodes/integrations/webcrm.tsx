import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WebCRMIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/webcrm.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WebCRMNode: NodeDefinition = {
    type: 'automation-webcrm', category: 'crm-sales', label: 'webCRM',
    description: 'Manage organisations, people, opportunities, activities and support cases',
    Icon: WebCRMIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WebCRMIcon} iconColor="" />),
};
