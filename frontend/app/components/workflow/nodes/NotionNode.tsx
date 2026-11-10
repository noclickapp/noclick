// Notion API automation node definition.
// Provides workflow integration with Notion for databases, pages, blocks, and search.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const NotionIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/notion-light.svg" dark="/icons/notion.svg" {...props} />
));
NotionIcon.displayName = 'NotionIcon';

const NotionNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={NotionIcon} iconColor="" />;
};

export const NotionNode: NodeDefinition = {
    type: 'automation-notion',
    label: 'Notion',
    description: 'Notion automation',
    Icon: NotionIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(NotionNodeComponent),
};
