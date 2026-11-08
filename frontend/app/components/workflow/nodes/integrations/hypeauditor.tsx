// Registers HypeAuditor in the workflow canvas and integration catalog.
// Uses the official provider icon and the backend-generated configuration form.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HypeAuditorIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hypeauditor.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const HypeAuditorNode: NodeDefinition = {
    type: 'automation-hypeauditor', category: 'marketing', label: 'HypeAuditor',
    description: 'Manage influencer media plans, social listening, creator reports and email unlocks',
    keywords: ['influencer', 'creator', 'social listening', 'media plan'],
    Icon: HypeAuditorIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HypeAuditorIcon} iconColor="" />),
};
