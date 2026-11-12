import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NumverifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/numverify.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/numverify-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const NumverifyNode: NodeDefinition = {
    type: 'automation-numverify', category: 'developer-tools', label: 'numverify',
    description: 'Validate phone numbers and look up carriers, line types and supported countries',
    keywords: ['phone validation', 'phone lookup', 'carrier', 'line type'],
    Icon: NumverifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NumverifyIcon} iconColor="" />),
};
