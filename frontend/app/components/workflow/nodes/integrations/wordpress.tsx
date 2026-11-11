// WordPress REST API automation node definition.
// Provides comprehensive workflow integration with WordPress for posts, pages, media, users, comments, and more.
// Supports WordPress.com OAuth, Application Passwords, and Basic Auth.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// WordPress's W mark, with a white file for dark mode
const WordPressIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/wordpress.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/wordpress-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

const WordPressNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={WordPressIcon} iconColor="" />;
};

export const WordPressNode: NodeDefinition = {
    type: 'automation-wordpress',
    label: 'WordPress',
    description: 'WordPress operations',
    Icon: WordPressIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(WordPressNodeComponent),
};
