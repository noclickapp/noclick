// Google Cloud Translation automation node definition.
// Provides workflow integration with Google Translate (v2 Basic API key + v3
// Advanced OAuth): translate, detect language, supported languages, romanize,
// document translation, batch translation, and glossaries.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GoogleTranslateIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-translate.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleTranslateIcon.displayName = 'GoogleTranslateIcon';

const GoogleTranslateNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleTranslateIcon} iconColor="" />;
};

export const GoogleTranslateNode: NodeDefinition = {
    type: 'automation-google-translate',
    label: 'Google Translate',
    description: 'Google Cloud Translation automation',
    Icon: GoogleTranslateIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleTranslateNodeComponent),
};
