// Bytescale exposes three scoped file/folder metadata reads in the native editor.
// The unchanged vendor wordmark is separate from generated operation forms.
import { memo, type SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const BytescaleIcon = ({ className, style }: SVGProps<SVGSVGElement>) => (
    <img src="/icons/bytescale.svg" alt="Bytescale" className={className} style={style} />
);

export const BytescaleNode: NodeDefinition = {
    type: 'automation-bytescale',
    label: 'Bytescale',
    description: 'Read scoped folder contents and file metadata',
    Icon: BytescaleIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={BytescaleIcon} iconColor="" />
    )),
};
