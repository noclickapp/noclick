import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MergeDevIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/merge-dev.svg" dark="/icons/merge-dev-dark.svg" className={className} style={style} />
);
export const MergeDevNode: NodeDefinition = {
    type: 'automation-merge-dev', category: 'developer-tools', label: 'Merge.dev',
    description: 'Automate unified HR, recruiting, CRM and ticketing data',
    Icon: MergeDevIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 42 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MergeDevIcon} iconColor="" />),
};
