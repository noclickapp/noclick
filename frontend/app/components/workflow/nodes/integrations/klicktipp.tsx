// KlickTipp's catalog and canvas definition, discovered by its integration type.
// The API schema supplies the operation forms; this file supplies its visual identity.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KlickTippIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/klicktipp.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/klicktipp-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const KlickTippNode: NodeDefinition = {
    type: 'automation-klicktipp', category: 'marketing', label: 'KlickTipp',
    description: 'Manage contacts, tags, data fields and opt-in processes',
    keywords: ['email marketing', 'subscribers', 'segmentation'],
    Icon: KlickTippIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KlickTippIcon} iconColor="" />),
};
