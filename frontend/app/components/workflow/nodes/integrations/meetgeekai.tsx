// MeetGeek's canvas and catalog definition uses the official service icon.
// The backend-generated schema supplies operations and API-key connection fields.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MeetGeekIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/meetgeekai.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const MeetGeekNode: NodeDefinition = {
    type: 'automation-meetgeekai', category: 'meetings', label: 'MeetGeek',
    description: 'Read meeting transcripts, summaries and insights; upload recordings and send a meeting bot',
    keywords: ['Meetgeek.ai', 'meeting notes', 'transcription'],
    Icon: MeetGeekIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MeetGeekIcon} iconColor="" />),
};
