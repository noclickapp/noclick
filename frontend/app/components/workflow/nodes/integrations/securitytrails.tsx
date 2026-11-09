import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SecurityTrailsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/securitytrails.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const SecurityTrailsNode: NodeDefinition = {
    type: 'automation-securitytrails',
    category: 'developer-tools',
    label: 'SecurityTrails',
    description:
        'Research domains, DNS and WHOIS; inspect ASI assets, exposures and tags',
    Icon: SecurityTrailsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function SecurityTrailsComponent(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={SecurityTrailsIcon} iconColor="" />
        );
    }),
};
