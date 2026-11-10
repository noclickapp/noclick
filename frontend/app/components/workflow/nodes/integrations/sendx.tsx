// Adds SendX audience metadata and finite CRM workflows to the native editor.
// The tile uses the publisher's unmodified SVG; automation effects are described in operation fields.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://www.sendx.io/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/sendx.svg" className={className} style={style} />
);

export const SendXNode: NodeDefinition = {
    type: 'automation-sendx', category: 'marketing', label: 'SendX',
    description: 'Read audience metadata and manage owned contacts, lists and tags',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 72 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
