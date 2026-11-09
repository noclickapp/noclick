import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SecIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sec.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SecNode: NodeDefinition = {
    type: 'automation-sec', category: 'finance-accounting', label: 'Sec',
    keywords: ['SEC', 'EDGAR', 'filer', 'Securities and Exchange Commission'],
    description: 'Manage EDGAR filer accounts, delegations and individuals, and check submission status',
    Icon: SecIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SecIcon} iconColor="" />),
};
