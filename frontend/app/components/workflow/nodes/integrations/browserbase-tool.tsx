// Adds Browserbase browser infrastructure to the workflow catalog and canvas.
// The definition uses the official service icon and the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BrowserbaseToolIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/browserbase-tool.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const BrowserbaseToolNode: NodeDefinition = {
    type: 'automation-browserbase-tool', category: 'developer-tools', label: 'Browserbase Tool',
    description: 'Create and release cloud browsers, reuse contexts, and inspect sessions and retrieve logs.',
    keywords: ['Browserbase', 'browser automation', 'Playwright', 'Puppeteer'],
    Icon: BrowserbaseToolIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BrowserbaseToolIcon} iconColor="" />),
};
