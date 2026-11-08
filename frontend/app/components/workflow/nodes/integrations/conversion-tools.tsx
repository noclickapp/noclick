// Conversion Tools uses the shared automation canvas component and generated schema.
// This definition makes file conversion operations discoverable in both palettes.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ConversionToolsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/conversion-tools.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ConversionToolsNode: NodeDefinition = {
    type: 'automation-conversion-tools', label: 'Conversion Tools',
    description: 'Upload files, convert documents and data, track tasks and download results',
    keywords: ['conversiontools', 'convert', 'PDF', 'XML', 'JSON', 'CSV', 'Excel'],
    Icon: ConversionToolsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ConversionToolsIcon} iconColor="" />),
};
