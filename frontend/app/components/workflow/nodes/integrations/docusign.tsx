// Docusign canvas definition, discovered alongside its generated metadata.
// Keeps the integration independent of shared node catalogs.
import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DocusignIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/docusign-brand-vector.svg" dark="/icons/docusign-brand-vector-dark.svg" className={className} style={style} {...props} ref={ref} />
));
DocusignIcon.displayName = 'DocusignIcon';

const DocusignNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={DocusignIcon} iconColor="" />
);

export const DocusignNode: NodeDefinition = {
    type: 'automation-docusign',
    label: 'Docusign',
    description: 'Docusign templates, envelopes, and signed documents',
    category: 'documents',
    Icon: DocusignIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(DocusignNodeComponent),
};
