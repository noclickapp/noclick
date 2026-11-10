import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CrunchbaseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/crunchbase.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CrunchbaseNode: NodeDefinition = {
    type: 'automation-crunchbase', category: 'content-research', label: 'Crunchbase',
    description: 'Look up and search companies, people, funding rounds, acquisitions and investments',
    Icon: CrunchbaseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CrunchbaseIcon} iconColor="" />),
};
