// Audienceful's catalog and canvas definition. Its schema and metadata are generated from the node.
// The official favicon identifies the service in the integration picker.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AudiencefulIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/audienceful.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const AudiencefulNode: NodeDefinition = {
    type: 'automation-audienceful', category: 'marketing', label: 'Audienceful',
    description: 'Sync contacts and consent, manage publications, send email and react to signed events',
    keywords: ['email marketing', 'newsletter', 'subscriber', 'webhook'],
    Icon: AudiencefulIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AudiencefulIcon} iconColor="" />),
};
