// Microsoft Word automation node definition.
// Provides comprehensive Word document operations via Microsoft Graph API.
// Supports document management, content operations, sharing, permissions, version control, and search.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Microsoft Word's product icon from Microsoft's Office CDN
const WordIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/word.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const WordNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={WordIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const WordNode: NodeDefinition = {
    type: 'automation-word',
    label: 'Word',
    description: 'Word automation',
    Icon: WordIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(WordNodeComponent),
};
