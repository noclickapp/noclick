import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DropboxSignIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/dropbox-sign.svg" dark="/icons/dropbox-sign-dark.svg" className={className} style={style} />
);

export const DropboxSignNode: NodeDefinition = {
    type: 'automation-dropbox-sign',
    category: 'documents',
    label: 'Dropbox Sign',
    description:
        'Send and manage signature requests, templates and signed document links',
    Icon: DropboxSignIcon,
    iconColor: '',
    keywords: ['HelloSign', 'eSignature', 'electronic signature'],
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function DropboxSignComponent(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={DropboxSignIcon} iconColor="" />
        );
    }),
};
