// Clearout node presentation for the workflow canvas and integration catalog.
// Configuration and credential fields come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ClearoutIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/clearout.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ClearoutNode: NodeDefinition = {
    type: 'automation-clearout', label: 'Clearout',
    description: 'Verify and find emails, manage bulk jobs and read account credits',
    Icon: ClearoutIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClearoutIcon} iconColor="" />),
};
