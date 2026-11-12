import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const SecurityTrailsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/securitytrails.svg" dark="/icons/securitytrails-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
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
