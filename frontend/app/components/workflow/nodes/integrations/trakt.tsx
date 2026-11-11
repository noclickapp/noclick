import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TraktIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => <>
    <img src="/icons/trakt.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
    <img src="/icons/trakt-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
</>;
export const TraktNode: NodeDefinition = {
    type: 'automation-trakt', category: 'media', label: 'Trakt',
    description: 'Track watched movies and episodes, manage watchlists, ratings, collections and personal lists.',
    keywords: ['movies', 'TV', 'watchlist', 'watched', 'ratings'],
    Icon: TraktIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TraktIcon} iconColor="" />),
};
