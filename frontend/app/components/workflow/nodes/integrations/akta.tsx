import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AktaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/akta.svg" dark="/icons/akta-dark.svg" className={className} style={style} />
);

export const AktaNode: NodeDefinition = {
    type: 'automation-akta', category: 'content-research', label: 'Akta',
    description: 'Research companies, news, reviews, jobs and traffic; generate company lists',
    Icon: AktaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AktaIcon} iconColor="" />),
};
