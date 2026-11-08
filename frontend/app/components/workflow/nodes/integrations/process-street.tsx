/** Process Street exposes workflow runs, tasks, and form data to the canvas.
 * This definition makes the self-registering integration discoverable with its official icon. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ProcessStreetIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/process-street.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ProcessStreetNode: NodeDefinition = {
    type: 'automation-process-street', category: 'productivity', label: 'Process Street',
    description: 'Automate workflow runs, tasks, assignments, form fields and comments',
    keywords: ['Process Street', 'checklists', 'workflow runs', 'process management'],
    Icon: ProcessStreetIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ProcessStreetIcon} iconColor="" />),
};
