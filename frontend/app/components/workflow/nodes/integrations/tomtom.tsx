import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TomTomIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tomtom.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TomTomNode: NodeDefinition = {
    type: 'automation-tomtom', category: 'industry', label: 'TomTom',
    description: 'Read map tiles, static maps and WMS/WMTS capabilities; includes withdrawn v1 copyright endpoints',
    Icon: TomTomIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TomTomIcon} iconColor="" />),
};
