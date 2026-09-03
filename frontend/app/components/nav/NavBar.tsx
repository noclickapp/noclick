import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Avatar, AvatarFallback, AvatarImage } from '~/components/ui/avatar';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import {
    Keyboard,
    LogOut,
    Search,
    Settings as SettingsIcon,
    Sun,
    Moon,
    Monitor,
    SunMoon,
} from 'lucide-react';
import { KeyHint } from '~/components/shared/KeyHint';
import { openCommandPalette, openKeyboardShortcuts } from '~/lib/shortcuts';
import { FaDiscord } from 'react-icons/fa6';
import { FeedbackButton } from '~/components/nav/FeedbackButton';
import { useAnalytics } from '~/lib/analytics';
import { useDebugToolsEnabled } from '~/hooks/useDebugToolsEnabled';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useValtioState } from '~/hooks/useValtioState';
import { useTheme } from '~/hooks/useTheme';
import { OrgSwitcher } from '~/components/organization/OrgSwitcher';
import { cn } from '~/lib/utils';
import { isLocalEdition } from '~/lib/edition';

// Shared account-menu row styling so every item stays consistent. duration-75
// overrides the base transition-colors (150ms) for a snappier hover.
const ACCOUNT_MENU_ITEM =
    'rounded-md cursor-pointer duration-75 text-foreground hover:bg-accent hover:text-accent-foreground dark:hover:text-zinc-100 focus:bg-accent focus:text-accent-foreground dark:focus:text-zinc-100';
const ACCOUNT_MENU_ITEM_DANGER =
    'rounded-md cursor-pointer duration-75 text-red-600 hover:bg-red-500/10 hover:text-red-700 focus:bg-red-500/10 focus:text-red-700 dark:text-red-400 dark:hover:text-red-300 dark:focus:text-red-300';

/** Count of things waiting on the user (approvals, questions, disconnected
 *  accounts, broken triggers). Fed by the dashboard overview; falls back to the
 *  live approval count so the badge is right before the overview has loaded. */
function DashboardBadge() {
    const [attention] = useValtioState<number | null>('noclick-ui', 'dashboardAttentionCount', null);
    const [approvals] = useValtioState<number>('noclick-ui', 'approvalPendingCount', 0);
    const count = attention ?? approvals;
    if (!count) return null;
    return (
        // Circle at minimum (min-width = height), a pill when the count is wider.
        <span className="inline-flex h-[20px] min-w-[20px] items-center justify-center rounded-full bg-primary px-1.5 text-primary-foreground">
            {/* Digits have no descender, so the centered line box leaves the ink high; nudge it down. */}
            <span className="translate-y-[0.5px] text-[12px] font-semibold tabular-nums leading-none">{count}</span>
        </span>
    );
}

interface NavBarProps {
    user: {
        email: string;
        avatar_url?: string;
        subscription_tier?: 'free' | 'plus' | 'pro' | 'enterprise';
    };
    selectedTab: string;
    onTabChange: (tab: string) => void;
    /** When true, sidebar is expanded and OrgSwitcher should hide from navbar */
    isSidebarExpanded?: boolean;
}

export function NavBar({
    user,
    selectedTab,
    onTabChange,
    isSidebarExpanded = true,
}: NavBarProps) {
    const navigate = useNavigate();
    const { logActivity } = useAnalytics();
    const debugToolsEnabled = useDebugToolsEnabled();

    // User preference to show/hide debug panel - can be hidden via DebugViewer and restored via /debug command
    const [debugPanelVisible, setDebugPanelVisible] =
        useCachedValtioState<boolean>('noclick-ui', 'debugPanelVisible', true);

    const [backendBranch, setBackendBranch] = useState('');
    const [theme, setTheme] = useTheme();

    // Fetch backend git branch (only when connected to localhost)
    useEffect(() => {
        const apiUrl = import.meta.env.VITE_API_URL || '';
        if (!apiUrl.includes('localhost')) return;
        fetch(`${apiUrl}/health/info`)
            .then((res) => res.json())
            .then((data) => {
                if (data.branch) setBackendBranch(data.branch);
            })
            .catch(() => {});
    }, []);


    // Listen for debug panel visibility events (needed because valtio subscription may not fire across components due to proxy reference changes)
    useEffect(() => {
        const handleDebugPanelShow = () => setDebugPanelVisible(true);
        const handleDebugPanelHide = () => setDebugPanelVisible(false);
        window.addEventListener(
            'noclick:debug-panel-show',
            handleDebugPanelShow
        );
        window.addEventListener(
            'noclick:debug-panel-hide',
            handleDebugPanelHide
        );
        return () => {
            window.removeEventListener(
                'noclick:debug-panel-show',
                handleDebugPanelShow
            );
            window.removeEventListener(
                'noclick:debug-panel-hide',
                handleDebugPanelHide
            );
        };
    }, [setDebugPanelVisible]);

    const handleLogout = async () => {
        const formData = new FormData();
        await fetch('/dashboard', {
            method: 'POST',
            body: formData,
        });
        navigate('/auth/login');
    };

    // Track when OrgSwitcher should be visible in navbar (with animation delay)
    const [showOrgSwitcher, setShowOrgSwitcher] = useState(!isSidebarExpanded);
    const animationTimeoutRef = useRef<NodeJS.Timeout | null>(null);

    // Handle sidebar expansion changes with animation timing
    useEffect(() => {
        if (animationTimeoutRef.current) {
            clearTimeout(animationTimeoutRef.current);
        }

        if (!isSidebarExpanded) {
            // Sidebar is collapsing - show OrgSwitcher after fade-out in sidebar
            animationTimeoutRef.current = setTimeout(() => {
                setShowOrgSwitcher(true);
            }, 150); // Delay to allow sidebar OrgSwitcher to fade out first
        } else {
            // Sidebar is expanding - hide OrgSwitcher immediately (it will fade out)
            setShowOrgSwitcher(false);
        }

        return () => {
            if (animationTimeoutRef.current) {
                clearTimeout(animationTimeoutRef.current);
            }
        };
    }, [isSidebarExpanded]);

    return (
        <>
            <nav className="border-b border-border bg-background text-foreground">
                <div className="h-14 flex items-center justify-between px-3 sm:px-4 overflow-hidden">
                    <div className="flex items-center gap-2 sm:gap-6 min-w-0">
                        {/* OrgSwitcher - only render when sidebar is collapsed to avoid gap */}
                        {showOrgSwitcher && (
                            <div className="animate-in fade-in slide-in-from-left-2 duration-200">
                                <OrgSwitcher
                                    userEmail={user.email}
                                    userAvatarUrl={user.avatar_url}
                                />
                            </div>
                        )}
                        <div className="flex gap-4">
                            <ShortcutTooltip keys={['G', 'W']}>
                                <button
                                    onClick={() => onTabChange('flow')}
                                    className={`px-3 py-1 rounded-md transition-colors ${
                                        selectedTab === 'flow'
                                            ? 'bg-accent text-accent-foreground dark:bg-foreground/10'
                                            : 'text-muted-foreground dark:text-white/60 hover:text-foreground'
                                    }`}
                                >
                                    Workflows
                                </button>
                            </ShortcutTooltip>
                            <ShortcutTooltip keys={['G', 'D']}>
                                <button
                                    onClick={() => onTabChange('dashboard')}
                                    className={`px-3 py-1 rounded-md transition-colors flex items-center gap-1.5 ${
                                        selectedTab === 'dashboard'
                                            ? 'bg-accent text-accent-foreground dark:bg-foreground/10'
                                            : 'text-muted-foreground dark:text-white/60 hover:text-foreground'
                                    }`}
                                >
                                    Dashboard
                                    <DashboardBadge />
                                </button>
                            </ShortcutTooltip>
                            {debugToolsEnabled && debugPanelVisible && (
                                <button
                                    onClick={() => onTabChange('debug')}
                                    className={`px-3 py-1 rounded-md transition-colors ${
                                        selectedTab === 'debug'
                                            ? 'bg-accent text-accent-foreground dark:bg-foreground/10'
                                            : 'text-muted-foreground dark:text-white/60 hover:text-foreground'
                                    }`}
                                >
                                    Debug
                                </button>
                            )}
                        </div>
                    </div>
                    <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
                        {/* Backend port & branch indicator - only shown when connected to localhost */}
                        {(() => {
                            const apiUrl = import.meta.env.VITE_API_URL || '';
                            const match = apiUrl.match(/localhost:(\d+)/);
                            return match ? (
                                <span className="hidden xl:inline text-xs font-mono text-muted-foreground dark:text-white/50 bg-secondary dark:bg-foreground/10 px-1.5 py-0.5 rounded">
                                    :{match[1]}
                                    {backendBranch ? ` (${backendBranch})` : ''}
                                </span>
                            ) : null;
                        })()}
                        {/* Search — opens the command palette (same as pressing mod+K) */}
                        <button
                            onClick={() => openCommandPalette()}
                            className="hidden lg:flex w-44 items-center justify-between rounded-lg bg-secondary dark:bg-foreground/[0.06] px-2.5 py-1.5 text-sm transition-colors hover:bg-accent dark:hover:bg-foreground/[0.1]"
                            title="Search and run commands"
                        >
                            <span className="flex items-center gap-2 text-muted-foreground">
                                <Search className="h-4 w-4" />
                                Search
                            </span>
                            <KeyHint keys={['mod', 'K']} />
                        </button>

                        {/* Community (Discord) - hidden until lg breakpoint */}
                        <button
                            onClick={() => {
                                logActivity('join_discord_clicked');
                                window.open(
                                    'https://discord.com/invite/sHC2mrnss8',
                                    '_blank'
                                );
                            }}
                            className="hidden lg:flex items-center gap-2 rounded-lg bg-secondary dark:bg-foreground/[0.06] px-2.5 py-1.5 text-sm text-foreground/80 transition-colors hover:bg-accent dark:hover:bg-foreground/[0.1]"
                            title="Join our Discord community"
                        >
                            <FaDiscord className="h-4 w-4 text-muted-foreground dark:text-zinc-500" />
                            Community
                        </button>

                        {/* Feedback / bug report - type and instantly submit.
                            Hidden below lg so the nav fits on tablets/phones, and on a
                            self-hosted instance, where it has no channel to land in. */}
                        {!isLocalEdition() && (
                            <div className="hidden lg:block">
                                <FeedbackButton />
                            </div>
                        )}

                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Avatar
                                    className="cursor-pointer hover:opacity-80"
                                    data-onboarding="user-menu"
                                >
                                    <AvatarImage
                                        src={
                                            user.avatar_url ||
                                            'https://github.com/shadcn.png'
                                        }
                                        alt="Profile picture"
                                    />
                                    <AvatarFallback className="bg-muted dark:bg-gray-700 text-foreground">
                                        {user.email
                                            .substring(0, 2)
                                            .toUpperCase()}
                                    </AvatarFallback>
                                </Avatar>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                className="w-72 rounded-xl p-1 duration-100"
                                align="end"
                                sideOffset={8}
                                data-onboarding="user-menu-dropdown"
                            >
                                {/* Account header — avatar, email, and the paid-plan badge */}
                                <div className="flex items-center gap-2.5 px-2 py-2">
                                    <Avatar className="h-9 w-9 shrink-0">
                                        <AvatarImage
                                            src={
                                                user.avatar_url ||
                                                'https://github.com/shadcn.png'
                                            }
                                            alt=""
                                        />
                                        <AvatarFallback className="bg-muted dark:bg-zinc-700 text-xs text-foreground">
                                            {user.email
                                                .substring(0, 2)
                                                .toUpperCase()}
                                        </AvatarFallback>
                                    </Avatar>
                                    <div className="min-w-0 flex-1">
                                        <div className="break-all text-sm font-medium leading-snug text-foreground">
                                            {user.email}
                                        </div>
                                    </div>
                                </div>
                                <DropdownMenuSeparator className="bg-border" />
                                <DropdownMenuGroup>
                                    <DropdownMenuItem
                                        className={ACCOUNT_MENU_ITEM}
                                        onClick={() => onTabChange('settings')}
                                        data-onboarding="settings"
                                    >
                                        <SettingsIcon className="mr-2 h-4 w-4 text-muted-foreground" />
                                        <span>Settings</span>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        className={ACCOUNT_MENU_ITEM}
                                        onClick={() => openKeyboardShortcuts()}
                                    >
                                        <Keyboard className="mr-2 h-4 w-4 text-muted-foreground" />
                                        <span>Shortcuts</span>
                                        <KeyHint
                                            keys={['mod', '/']}
                                            className="ml-auto"
                                        />
                                    </DropdownMenuItem>
                                    {/* Theme picker — a System/Light/Dark segmented control;
                                preventDefault keeps the menu open so the flip is visible */}
                                    <DropdownMenuItem
                                        className={cn(
                                            ACCOUNT_MENU_ITEM,
                                            'cursor-default focus:bg-transparent'
                                        )}
                                        onSelect={(e) => e.preventDefault()}
                                    >
                                        <SunMoon className="mr-2 h-4 w-4 text-muted-foreground" />
                                        <span>Theme</span>
                                        <div className="ml-auto flex items-center gap-0.5 p-0.5 rounded-full bg-accent dark:bg-secondary/60 border border-border">
                                            {(
                                                [
                                                    {
                                                        value: 'system',
                                                        icon: Monitor,
                                                        label: 'System theme',
                                                    },
                                                    {
                                                        value: 'light',
                                                        icon: Sun,
                                                        label: 'Light theme',
                                                    },
                                                    {
                                                        value: 'dark',
                                                        icon: Moon,
                                                        label: 'Dark theme',
                                                    },
                                                ] as const
                                            ).map(
                                                ({
                                                    value,
                                                    icon: OptIcon,
                                                    label,
                                                }) => (
                                                    <button
                                                        key={value}
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            setTheme(value);
                                                        }}
                                                        aria-label={label}
                                                        aria-pressed={
                                                            theme === value
                                                        }
                                                        className={cn(
                                                            'p-1 rounded-full transition-colors',
                                                            theme === value
                                                                ? 'bg-card shadow-sm text-foreground dark:bg-muted-foreground/30 dark:shadow-none'
                                                                : 'text-muted-foreground dark:text-white/60 hover:text-foreground'
                                                        )}
                                                    >
                                                        <OptIcon className="h-3.5 w-3.5" />
                                                    </button>
                                                )
                                            )}
                                        </div>
                                    </DropdownMenuItem>
                                </DropdownMenuGroup>
                                <DropdownMenuSeparator className="bg-border" />
                                <DropdownMenuItem
                                    className={ACCOUNT_MENU_ITEM_DANGER}
                                    onClick={handleLogout}
                                >
                                    <LogOut className="mr-2 h-4 w-4" />
                                    <span>Log out</span>
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                </div>
            </nav>
        </>
    );
}
