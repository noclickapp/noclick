// Browserless provides hosted browser tasks and persistent automation resources.
// This definition makes its generated schema discoverable in both node catalogs.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const BrowserlessIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/browserless.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BrowserlessIcon.displayName = 'BrowserlessIcon';

export const BrowserlessNode: NodeDefinition = {
    type: 'automation-browserless',
    label: 'Browserless',
    category: 'developer-tools',
    description: 'Capture screenshots and PDFs, scrape pages, search, crawl and manage browser profiles',
    keywords: ['browser', 'scraping', 'screenshots', 'pdf', 'crawl', 'lighthouse'],
    Icon: BrowserlessIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BrowserlessIcon} iconColor="" />),
};
