// Docspell exposes closed folder/tag metadata reads in the native editor.
// The unchanged official PNG wordmark is separate from generated operation forms.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const DocspellIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/docspell.svg" alt="" className={className} style={{ ...style, objectFit: "contain" }} {...props} />
    ),
);
DocspellIcon.displayName = 'DocspellIcon';

export const DocspellNode: NodeDefinition = {
    type: 'automation-docspell',
    label: 'Docspell',
    description: 'Read scoped folder and tag metadata',
    Icon: DocspellIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={DocspellIcon} iconColor="" />
    )),
};
