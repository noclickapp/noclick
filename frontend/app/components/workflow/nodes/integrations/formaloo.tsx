import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const FormalooIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/formaloo.svg" dark="/icons/formaloo-dark.svg" className={className} style={style} />
);

export const FormalooNode: NodeDefinition = {
    type: 'automation-formaloo', category: 'forms', label: 'Formaloo',
    description: 'Automate forms, submissions, folders and tags; react to submission events',
    Icon: FormalooIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FormalooIcon} iconColor="" />),
};
