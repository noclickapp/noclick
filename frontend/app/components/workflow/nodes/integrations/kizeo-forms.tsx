import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const KizeoFormsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/kizeo-forms.svg" className={className} style={style} />
);

export const KizeoFormsNode: NodeDefinition = {
    type: 'automation-kizeo-forms', category: 'forms', label: 'Kizeo Forms',
    description: 'Automate forms, submissions, external lists, users and groups',
    Icon: KizeoFormsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KizeoFormsIcon} iconColor="" />),
};
