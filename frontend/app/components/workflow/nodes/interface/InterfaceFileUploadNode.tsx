// Interface file upload node for rendering a drop zone in the workflow canvas.
// Renders the actual FileUpload block UI inside ReactFlow.

import { NodeProps } from '@xyflow/react';
import { Upload } from 'lucide-react';
import InterfaceNode from './InterfaceNode';
import type { NodeDefinition } from '../types';

const DIMENSIONS = { width: 350, height: 160, iconSize: 48 };

const InterfaceFileUploadNodeComponent = (props: NodeProps) => {
    return <InterfaceNode {...props} Icon={Upload} iconColor="text-lime-400" />;
};

export const InterfaceFileUploadNode: NodeDefinition = {
    type: 'interface-file-upload',
    label: 'File Upload',
    description: 'Drop zone with file picker',
    Icon: Upload,
    iconColor: 'text-lime-400',
    dimensions: DIMENSIONS,
    component: InterfaceFileUploadNodeComponent,
};
