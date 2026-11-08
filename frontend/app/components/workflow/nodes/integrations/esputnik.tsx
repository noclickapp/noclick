import { forwardRef, memo, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

export const ESputnikIcon = forwardRef<HTMLImageElement, Pick<ImgHTMLAttributes<HTMLImageElement>, 'className' | 'style'>>(
    ({ className, style }, ref) => <img ref={ref} src="/icons/esputnik.svg" alt="eSputnik" className={className} style={{ ...style, objectFit: 'contain' }} />,
);
ESputnikIcon.displayName = 'ESputnikIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={ESputnikIcon} iconColor="" />;
export const ESputnikNode: NodeDefinition = {
    type: 'automation-esputnik', category: 'marketing', label: 'eSputnik (Yespo)',
    description: 'Read account, contact field schema, contact cards and broadcast metadata',
    keywords: ['eSputnik', 'Yespo', 'contacts', 'audience', 'broadcast', 'reporting'],
    Icon: ESputnikIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(Component),
};
