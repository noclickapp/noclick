import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const GetanyapiIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/getanyapi.svg"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
GetanyapiIcon.displayName = 'GetanyapiIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const GetanyapiNode: NodeDefinition = {
    type: 'automation-getanyapi',
    label: 'Getanyapi',
    description: 'Wallet, catalog, scraping, search and enrichment',
    category: 'content-research',
    Icon: GetanyapiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function GetanyapiComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={GetanyapiIcon} iconColor="" />;
    }),
};
