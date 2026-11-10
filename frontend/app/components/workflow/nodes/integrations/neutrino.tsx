import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NeutrinoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/neutrino.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const NeutrinoNode: NodeDefinition = {
    type: 'automation-neutrino', category: 'developer-tools', label: 'Neutrino',
    description: 'Validate contacts, enrich IPs and domains, clean content and send verification codes',
    Icon: NeutrinoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NeutrinoIcon} iconColor="" />),
};
