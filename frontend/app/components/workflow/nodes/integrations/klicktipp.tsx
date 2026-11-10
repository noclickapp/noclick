// KlickTipp's catalog and canvas definition, discovered by its integration type.
// The API schema supplies the operation forms; this file supplies its visual identity.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const KlickTippIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/klicktipp.svg" dark="/icons/klicktipp-dark.svg" className={className} style={style} />
);

export const KlickTippNode: NodeDefinition = {
    type: 'automation-klicktipp', category: 'marketing', label: 'KlickTipp',
    description: 'Manage contacts, tags, data fields and opt-in processes',
    keywords: ['email marketing', 'subscribers', 'segmentation'],
    Icon: KlickTippIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KlickTippIcon} iconColor="" />),
};
