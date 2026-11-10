import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RawgIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rawg-video-games-database.jpg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const RawgVideoGamesDatabaseNode: NodeDefinition = {
    type: 'automation-rawg-video-games-database', category: 'media', label: 'RAWG Video Games Database',
    description: 'Search games and read game details, screenshots, stores, creators and catalog metadata',
    Icon: RawgIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RawgIcon} iconColor="" />),
};
