// Coassemble's own definition makes its node discoverable in the workflow editor.
// The provider's official site icon identifies its headless course API.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CoassembleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/coassemble.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/coassemble-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const CoassembleNode: NodeDefinition = {
    type: 'automation-coassemble', category: 'courses', label: 'Coassemble',
    description: 'Manage courses, collections, learners and course tracking in Coassemble',
    keywords: ['learning', 'training', 'lms', 'headless', 'courses'],
    Icon: CoassembleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CoassembleIcon} iconColor="" />),
};
