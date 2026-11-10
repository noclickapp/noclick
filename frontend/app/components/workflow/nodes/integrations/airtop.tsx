import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AirtopIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/airtop.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/airtop-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const AirtopNode: NodeDefinition = {
    type: 'automation-airtop', category: 'ai', label: 'Airtop',
    description: 'Automate browser sessions, interact with pages and extract content',
    Icon: AirtopIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AirtopIcon} iconColor="" />),
};
