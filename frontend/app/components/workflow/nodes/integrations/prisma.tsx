import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const PrismaIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/prisma.svg"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
PrismaIcon.displayName = 'PrismaIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const PrismaNode: NodeDefinition = {
    type: 'automation-prisma',
    label: 'Prisma',
    description:
        'Manage Prisma Postgres projects, databases, connections and backups',
    category: 'databases-storage',
    keywords: ['postgres', 'database', 'backups', 'management api'],
    Icon: PrismaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PrismaIcon} iconColor="" />
    )),
};
