// The console's frame, laid out like the app's: on a laptop the sidebar (its
// width dragged from its edge, folded to a rail with ⌘\, both shared with the
// app) beside the page; on a phone a slim bar whose menu opens the same
// sidebar as a sheet.
import { useState, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Menu } from 'lucide-react';
import { Link } from 'react-router';
import { cn } from '@/ui/utils';
import {
    SIDEBAR_ICON_BUTTON,
    SIDEBAR_SHEET,
    SIDEBAR_SHEET_OVERLAY,
    SheetClose,
    SidebarColumn,
    SidebarSearch,
    SidebarToggle,
    useSidebarShortcut,
} from '@/ui/sidebarParts';
import { useSidebarCollapsed } from '@/ui/sidebarPanel';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { ConsolePalette, openConsolePalette } from './ConsolePalette';
import { ConsoleSidebarContent } from './Sidebar';
import { READABLE_PLACEHOLDERS } from './ui/tokens';
import type { SectionDef, SectionId } from './sections';

function PhoneBar({ active }: { active: SectionId | null }) {
    const { basePath } = useConsole();
    const [open, setOpen] = useState(false);
    const close = () => setOpen(false);
    return (
        <header className="flex h-12 shrink-0 items-center gap-1 px-2 md:hidden">
            <Dialog.Root open={open} onOpenChange={setOpen}>
                <Dialog.Trigger aria-label="Open menu" className={SIDEBAR_ICON_BUTTON}>
                    <Menu className="h-5 w-5" strokeWidth={1.75} />
                </Dialog.Trigger>
                <Dialog.Portal>
                    <Dialog.Overlay className={SIDEBAR_SHEET_OVERLAY} />
                    <Dialog.Content className={SIDEBAR_SHEET}>
                        <Dialog.Title className="sr-only">Developer console</Dialog.Title>
                        <Dialog.Description className="sr-only">Console sections and your account</Dialog.Description>
                        <ConsoleSidebarContent active={active} collapsed={false} headerEnd={<SheetClose onClose={close} />} onNavigate={close} />
                    </Dialog.Content>
                </Dialog.Portal>
            </Dialog.Root>
            <Link to={basePath} className="min-w-0 flex-1 truncate px-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground">
                Developers
            </Link>
            <SidebarSearch onSearch={openConsolePalette} />
        </header>
    );
}

export function ConsoleShell({ section, children }: { section: SectionDef | null; children: ReactNode }) {
    const active = section?.navId ?? section?.id ?? null;
    const [collapsed, setCollapsed] = useSidebarCollapsed();
    useSidebarShortcut(collapsed, setCollapsed);
    return (
        <div className={cn('flex h-dvh flex-col bg-background pt-[env(safe-area-inset-top)] text-foreground md:flex-row md:pt-0', READABLE_PLACEHOLDERS)}>
            <PhoneBar active={active} />
            <SidebarColumn collapsed={collapsed} className="relative hidden h-full shrink-0 md:block">
                <ConsoleSidebarContent active={active} collapsed={collapsed} headerEnd={<SidebarToggle collapsed={collapsed} onCollapsedChange={setCollapsed} />} />
            </SidebarColumn>
            <main id="developer-console-main" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
                <div className="mx-auto w-full max-w-[1160px] px-4 pb-24 pt-6 sm:px-8 sm:pt-9">{children}</div>
            </main>
            <ConsolePalette />
        </div>
    );
}
