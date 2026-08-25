// Reddit workflow node component.
// Provides Reddit API operations in visual workflow editor.

import { memo, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Reddit Snoo icon (official Reddit logo)
const RedditIcon = ({ className, style, ...props }: SVGProps<SVGSVGElement>) => (
    <svg viewBox="0 0 24 24" className={className} style={style} {...props}>
        <circle cx="12" cy="12" r="12" fill="#FF4500" />
        <path
            fill="#FFFFFF"
            d="M19.5 12a1.5 1.5 0 0 0-2.5-1.12 7.36 7.36 0 0 0-4-1.26l.69-3.21 2.22.49a1.07 1.07 0 1 0 .11-.52l-2.49-.55a.27.27 0 0 0-.31.2l-.76 3.6a7.36 7.36 0 0 0-4.08 1.26 1.5 1.5 0 1 0-1.65 2.45 2.88 2.88 0 0 0 0 .45c0 2.3 2.68 4.16 5.99 4.16s5.99-1.86 5.99-4.16a2.88 2.88 0 0 0 0-.45 1.5 1.5 0 0 0 .79-1.34Z"
        />
        <circle cx="9.5" cy="12.5" r="1" fill="#FF4500" />
        <circle cx="14.5" cy="12.5" r="1" fill="#FF4500" />
        <path
            fill="#FF4500"
            d="M9.75 15.38a.26.26 0 0 0 0 .37 3.35 3.35 0 0 0 4.5 0 .26.26 0 0 0 0-.37.26.26 0 0 0-.37 0 2.82 2.82 0 0 1-3.76 0 .26.26 0 0 0-.37 0Z"
        />
    </svg>
);

export const RedditNode: NodeDefinition = {
    type: 'automation-reddit',
    label: 'Reddit',
    description: 'Reddit automation',
    Icon: RedditIcon as any,
    iconColor: '', // Custom SVG, no Tailwind color needed
    dimensions: DIMENSIONS,
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={RedditIcon as any} iconColor="" />
    )),
};
