import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GTmetrixIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gtmetrix.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GTmetrixNode: NodeDefinition = {
    type: 'automation-gtmetrix', category: 'monitoring', label: 'GTmetrix',
    description: 'Run performance tests and manage reports, monitored pages and tags',
    Icon: GTmetrixIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GTmetrixIcon} iconColor="" />),
};
