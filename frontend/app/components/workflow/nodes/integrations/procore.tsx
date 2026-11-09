// Procore catalog and canvas definition. The schema supplies its operation form;
// this definition supplies the official mark and industry catalog placement.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ProcoreIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/procore.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ProcoreNode: NodeDefinition = {
    type: 'automation-procore', category: 'industry', label: 'Procore',
    description: 'Automate projects, vendors, RFIs, submittals, daily logs and locations',
    Icon: ProcoreIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ProcoreIcon} iconColor="" />),
};
