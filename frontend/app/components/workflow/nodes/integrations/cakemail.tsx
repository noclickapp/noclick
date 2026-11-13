import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CakemailIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/cakemail.svg" className={className} style={style} />
);
export const CakemailNode: NodeDefinition = {
    type: 'automation-cakemail', category: 'marketing', label: 'Cakemail',
    description: 'Manage contacts, campaigns and lists; react to bounces, complaints and unsubscribes',
    Icon: CakemailIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CakemailIcon} iconColor="" />),
};
