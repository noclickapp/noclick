import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PlaterecognizerIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/platerecognizer.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const PlaterecognizerNode: NodeDefinition = {
    type: 'automation-platerecognizer',
    label: 'Plate Recognizer',
    category: 'ai',
    description:
        'Recognize plates and identifiers, monitor cameras and submit videos',
    keywords: ['platerecognizer', 'ALPR', 'ANPR', 'OCR', 'VIN', 'VisionAlert'],
    Icon: PlaterecognizerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function PlaterecognizerComponent(props: NodeProps) {
        return (
            <AutomationNode
                {...props}
                Icon={PlaterecognizerIcon}
                iconColor=""
            />
        );
    }),
};
