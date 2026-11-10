import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoogleBooksIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/google-books.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const GoogleBooksNode: NodeDefinition = {
    type: 'automation-google-books', category: 'google', label: 'Google Books',
    description: 'Search books, manage your bookshelves and annotations, and watch annotation updates.',
    keywords: ['ebooks', 'reading', 'library', 'Google Play Books'],
    Icon: GoogleBooksIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoogleBooksIcon} iconColor="" />),
};
