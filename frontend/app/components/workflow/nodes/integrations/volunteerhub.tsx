import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VolunteerHubIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/volunteerhub.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const VolunteerHubNode: NodeDefinition = {
    type: 'automation-volunteerhub', category: 'nonprofit', label: 'VolunteerHub',
    description: 'Read volunteers, events, donations and groups; manage user group memberships',
    keywords: ['volunteers', 'nonprofit', 'hours', 'fundraising'],
    Icon: VolunteerHubIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VolunteerHubIcon} iconColor="" />),
};
