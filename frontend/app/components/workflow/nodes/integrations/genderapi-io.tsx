// Exposes the GenderAPI.io V2 actions in the workflow catalog and canvas.
// Configuration and credentials use the generated integration schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GenderapiIoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/genderapi-io.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GenderapiIoNode: NodeDefinition = {
    type: 'automation-genderapi-io', label: 'GenderAPI.io',
    category: 'crm-sales',
    description: 'Predict from names, emails and usernames, validate phones and read credit usage',
    Icon: GenderapiIoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GenderapiIoIcon} iconColor="" />),
};
