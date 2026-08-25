// Interface node for HTML or React/JSX components on the workflow canvas.

import { NodeProps } from '@xyflow/react';
import { AppWindow } from 'lucide-react';
import InterfaceNode from './InterfaceNode';
import type { NodeDefinition } from '../types';

const DIMENSIONS = { width: 1150, height: 800, iconSize: 48 };

const InterfaceHtmlReactNodeComponent = (props: NodeProps) => {
    return <InterfaceNode {...props} Icon={AppWindow} iconColor="text-violet-600 dark:text-violet-400" />;
};

export const InterfaceHtmlReactNode: NodeDefinition = {
    type: 'interface-html-react',
    label: 'Component',
    description: 'HTML or React/JSX component',
    Icon: AppWindow,
    iconColor: 'text-violet-600 dark:text-violet-400',
    dimensions: DIMENSIONS,
    component: InterfaceHtmlReactNodeComponent,
};
