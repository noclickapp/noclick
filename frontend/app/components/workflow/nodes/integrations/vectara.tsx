// Native Vectara corpus and document workflow node.
// Reuses the standard automation settings and the exact official logo asset.
// Corpus search explicitly disables generation in the native backend.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const VectaraIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => <img {...props} ref={ref} alt="" src="/icons/vectara.png" style={{ ...style, objectFit: 'contain' }} />,
);
VectaraIcon.displayName = 'VectaraIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={VectaraIcon} iconColor="" />;
export const VectaraNode: NodeDefinition = {
    type: 'automation-vectara', category: 'vector-db', label: 'Vectara',
    description: 'Corpus documents, indexing, metadata, jobs and search without generation',
    Icon: VectaraIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(Component),
};
