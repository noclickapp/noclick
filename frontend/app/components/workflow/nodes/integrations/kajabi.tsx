import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Kajabi's K from kajabi.com, with a white file for dark mode; source and edits are in their provenance files.
const KajabiIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <>
        <img
            src="/icons/kajabi.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }}
        />
        <img
            src="/icons/kajabi-dark.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }}
        />
    </>
);

export const KajabiNode: NodeDefinition = {
    type: 'automation-kajabi',
    category: 'courses',
    label: 'Kajabi',
    description:
        'Create and tag contacts, manage offer access, and sync customers and purchases',
    keywords: ['courses', 'memberships', 'contacts', 'offers', 'purchases'],
    Icon: KajabiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={KajabiIcon} iconColor="" />
    )),
};
