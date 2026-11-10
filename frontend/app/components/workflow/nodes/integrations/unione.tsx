import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UnioneIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/unione.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const UnioneNode: NodeDefinition = {
    type: 'automation-unione', category: 'marketing', label: 'UniOne',
    description: 'Send transactional email and manage templates, suppressions, domains and exports',
    Icon: UnioneIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UnioneIcon} iconColor="" />),
};
