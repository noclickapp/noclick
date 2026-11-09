// Cloro provides structured AI answers and search results for research workflows.
// This definition makes its native operations discoverable in the catalog and canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CloroIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cloro.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CloroNode: NodeDefinition = {
    type: 'automation-cloro', category: 'content-research', label: 'Cloro',
    description: 'Monitor AI answers and search results, submit async tasks and check credits',
    Icon: CloroIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CloroIcon} iconColor="" />),
};
