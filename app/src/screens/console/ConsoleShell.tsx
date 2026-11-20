// The console's frame: the app's (screens/shell/AppShell), with the console's own sidebar in it (its sections, the way
// back to the app, its search: Sidebar.tsx) and its own palette. On a laptop the sidebar (its width dragged from its
// edge, folded to a rail with ⌘\, both shared with the app) beside the page; on a phone a slim bar whose menu opens the
// same sidebar as a sheet, the console's name leading to its overview and search at the bar's end.
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { AppShell } from '@/screens/shell/AppShell';
import { PhoneBarActions } from '@/ui/phoneBar';
import { SidebarSearch } from '@/ui/sidebarParts';
import { useSidebarCollapsed } from '@/ui/sidebarPanel';
import { useIsMobile } from '@/ui/useIsMobile';
import { cn } from '@/ui/utils';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { ConsolePalette, openConsolePalette } from './ConsolePalette';
import { ConsoleSidebarContent } from './Sidebar';
import { READABLE_PLACEHOLDERS } from './ui/tokens';
import type { SectionDef } from './sections';

export function ConsoleShell({ section, children }: { section: SectionDef | null; children: ReactNode }) {
    const active = section?.navId ?? section?.id ?? null;
    const { basePath } = useConsole();
    // A phone below the laptop's breakpoint, as the console's pages lay themselves out (Tailwind's `md`).
    const isMobile = useIsMobile();
    const [collapsed, setCollapsed] = useSidebarCollapsed();
    return (
        <>
            <AppShell
                isMobile={isMobile}
                sidebar={(frame) => <ConsoleSidebarContent {...frame} active={active} />}
                collapsed={collapsed}
                onCollapsedChange={setCollapsed}
                title={<Link to={basePath}>Developers</Link>}
                builder={null}
                builderShown={false}
                builderWidth={0}
                animate
            >
                <PhoneBarActions>
                    <SidebarSearch onSearch={openConsolePalette} />
                </PhoneBarActions>
                <div id="developer-console-main" className={cn('h-full overflow-y-auto text-foreground', READABLE_PLACEHOLDERS)}>
                    <div className="mx-auto w-full max-w-[1160px] px-4 pb-24 pt-6 sm:px-8 sm:pt-9">{children}</div>
                </div>
            </AppShell>
            <ConsolePalette />
        </>
    );
}
