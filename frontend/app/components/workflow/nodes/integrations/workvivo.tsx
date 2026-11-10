// Workvivo connects tenant-scoped employee-experience metadata and draft pages.
// Static app credentials retain the organisation and regional API base.
// The official mark retains its proportions in the native node icon slot.
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Official developer-site logo; see the icon's provenance sidecar.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/workvivo.svg" dark="/icons/workvivo-dark.svg" className={className} style={style} />
);

export const WorkvivoNode: NodeDefinition = {
    type: 'automation-workvivo',
    label: 'Workvivo',
    description: 'User, space, content and event metadata with draft page management',
    category: 'communication',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
