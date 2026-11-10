/** HubFit's discoverable canvas and integration catalog definition.
 * Uses the provider's official mark and groups coaching automation under Industry. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HubFitIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hubfit.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const HubFitNode: NodeDefinition = {
    type: 'automation-hubfit', category: 'industry', label: 'HubFit',
    description: 'Manage coaching clients, check-ins, messages, notes and tasks, and react to client activity',
    keywords: ['fitness', 'coaching', 'workout', 'check-in', 'questionnaire', 'package'],
    Icon: HubFitIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HubFitIcon} iconColor="" />),
};
