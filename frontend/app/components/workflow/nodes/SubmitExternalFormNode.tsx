// Submit External Form node definition.
// Triggers a different NoClick flow by submitting one of its form triggers: the
// config renders the target form's fields to fill, and on execute those values
// are submitted to the form (starting that flow). The `workflow`, `form`, and
// `inputs` config values are literal references, so the node stays copy-pastable.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { ClipboardCheck } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const SubmitExternalFormNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ClipboardCheck} iconColor="text-foreground" />;
};

export const SubmitExternalFormNode: NodeDefinition = {
    type: 'automation-submit-external-form',
    label: 'Submit External Form',
    description: 'Trigger another flow via its form',
    Icon: ClipboardCheck,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(SubmitExternalFormNodeComponent),
};
