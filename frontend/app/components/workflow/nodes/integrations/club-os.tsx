// Club OS actions and poll triggers use the shared schema-driven workflow panel.
// This definition makes the integration discoverable in the canvas and public catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ClubOSIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/club-os.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const ClubOSNode: NodeDefinition = {
    type: 'automation-club-os',
    category: 'industry',
    label: 'Club OS',
    description:
        'Monitor leads and sales events, read club reports, and manage training bookings',
    keywords: ['gym', 'fitness', 'club', 'personal training'],
    Icon: ClubOSIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ClubOSIcon} iconColor="" />
    )),
};
