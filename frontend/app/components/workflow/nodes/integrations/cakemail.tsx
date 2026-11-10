import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const CakemailIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cakemail.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);
export const CakemailNode: NodeDefinition = {
    type: 'automation-cakemail', category: 'marketing', label: 'Cakemail',
    description: 'Manage contacts, campaigns and lists; react to bounces, complaints and unsubscribes',
    Icon: CakemailIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CakemailIcon} iconColor="" />),
};
