import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const WhoisfreaksIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/whoisfreaks.svg" dark="/icons/whoisfreaks-dark.svg" className={className} style={style} />
);

export const WhoisfreaksNode: NodeDefinition = {
    type: 'automation-whoisfreaks',
    category: 'developer-tools',
    label: 'WhoisFreaks',
    description:
        'Research WHOIS, DNS, SSL, domain availability and IP intelligence',
    Icon: WhoisfreaksIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function WhoisfreaksComponent(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={WhoisfreaksIcon} iconColor="" />
        );
    }),
};
