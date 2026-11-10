import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WhoisfreaksIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <>
        <img
            src="/icons/whoisfreaks.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} dark:hidden`}
            style={
                {
                    ...style,
                    '--brand-invert': 0,
                    objectFit: 'contain',
                } as CSSProperties
            }
        />
        <img
            src="/icons/whoisfreaks-dark.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} hidden dark:block`}
            style={
                {
                    ...style,
                    '--brand-invert': 0,
                    objectFit: 'contain',
                } as CSSProperties
            }
        />
    </>
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
