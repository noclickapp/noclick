import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AddressfinderIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/addressfinder.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AddressfinderIcon.displayName = 'AddressfinderIcon';

export const AddressfinderNode: NodeDefinition = {
    type: 'automation-addressfinder',
    label: 'Addressfinder',
    description: 'Find addresses and locations, enrich address metadata, and verify addresses, email and phone numbers',
    category: 'developer-tools',
    keywords: ['address validation', 'geocoding', 'autocomplete', 'New Zealand', 'Australia'],
    Icon: AddressfinderIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AddressfinderIcon} iconColor="" />),
};
