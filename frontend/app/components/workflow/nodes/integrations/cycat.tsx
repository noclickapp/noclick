import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CycatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cycat.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CycatNode: NodeDefinition = {
    type: 'automation-cycat', category: 'content-research', label: 'CyCAT.org API',
    description: 'Search cybersecurity resources, explore relationships and propose resources for review. Public API; no account required.',
    keywords: ['cycat', 'cybersecurity', 'threat intelligence', 'sigma', 'MITRE ATT&CK'],
    Icon: CycatIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CycatIcon} iconColor="" />),
};
