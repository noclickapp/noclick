// Bitrise exposes current protected app, branch and build metadata reads.
// Bitrise's own Bit Bot mark (its site's SVG favicon); source and edits are in its provenance file.
import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';

export const BitriseIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/bitrise.svg" alt="Bitrise"
        style={{ objectFit: 'contain', ...style }} />
);
const BitriseNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={BitriseIcon} iconColor="" />;
export const BitriseNode: NodeDefinition = {
    type: 'automation-bitrise', category: 'developer-tools', label: 'Bitrise', description: 'Read protected apps, branches and build metadata',
    Icon: BitriseIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: BitriseNodeComponent,
};
