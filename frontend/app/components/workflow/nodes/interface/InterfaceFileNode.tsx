// Universal interface file node — embeds any uploaded file in the workflow
// canvas and renders the right viewer (image, audio, video, PDF, or a download
// card) based on the detected type. Renders the File block UI inside ReactFlow.

import { NodeProps } from '@xyflow/react';
import { MultimediaIcon } from './interfaceIcons';
import InterfaceNode from './InterfaceNode';
import type { NodeDefinition } from '../types';

const DIMENSIONS = { width: 350, height: 240, iconSize: 48 };

const InterfaceFileNodeComponent = (props: NodeProps) => {
    return <InterfaceNode {...props} Icon={MultimediaIcon} iconColor="text-orange-600 dark:text-orange-400" />;
};

export const InterfaceFileNode: NodeDefinition = {
    type: 'interface-file',
    label: 'Multimedia',
    description: 'Any file — image, audio, video, PDF, or download',
    Icon: MultimediaIcon,
    iconColor: 'text-orange-600 dark:text-orange-400',
    dimensions: DIMENSIONS,
    component: InterfaceFileNodeComponent,
};
