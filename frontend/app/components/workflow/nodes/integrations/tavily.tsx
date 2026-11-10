import { memo, type ImgHTMLAttributes } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

// Both marks are official Tavily assets. The UI's class theme selects the
// appropriate supplied color without altering the logo.

// Unmodified compact brand asset from https://www.tavily.com/
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/tavily-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const TavilyIcon: SvgIconComponent = ({
    className,
    style,
}: ImgHTMLAttributes<HTMLImageElement>) => (
    <span className={className} style={style}>
        <img
            src="/icons/tavily.svg"
            alt=""
            className="h-full w-full dark:hidden"
        />
        <img
            src="/icons/tavily-dark.svg"
            alt=""
            className="hidden h-full w-full dark:block"
        />
    </span>
);

export const TavilyNode: NodeDefinition = {
    type: 'automation-tavily',
    label: 'Tavily',
    description: 'Web search, extraction, crawling, mapping, and research',
    category: 'ai',
    keywords: ['web search', 'web research', 'crawl', 'extract'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
    )),
};
