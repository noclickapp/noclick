// An app or an AI company in Connections' catalog: its mark and name, whether you have an account with it (and
// whether one needs reconnecting), and Connect.
import type { ReactNode } from 'react';
import { AlertCircle, Check } from 'lucide-react';
import { BUTTON_OUTLINE_SM } from '@/ui/buttons';
import { Tile } from '@/ui/Tile';

/** Something in the catalog: an app or an AI account. Connect always adds an account, a second Gmail as easily
 *  as the first; once you have one, the rest of the tile opens it. */
export function CatalogTile({
    mark,
    title,
    accounts,
    idle,
    onManage,
    onConnect,
    testId,
}: {
    mark: ReactNode;
    title: string;
    /** The accounts you have with it, each with what keeps it from working, if anything. */
    accounts: readonly { problem?: string }[];
    /** The line under the name before anything is connected (an AI company's subscription). */
    idle?: string;
    onManage: () => void;
    onConnect: () => void;
    testId?: string;
}) {
    const connected = accounts.length;
    const broken = accounts.some((a) => a.problem);
    return (
        <Tile
            mark={mark}
            title={title}
            detail={
                connected ? (
                    <span className="inline-flex items-center gap-1">
                        {broken ? (
                            <>
                                <AlertCircle className="h-3.5 w-3.5 text-red-600 dark:text-red-400" strokeWidth={2.25} />
                                Needs reconnecting
                            </>
                        ) : (
                            <>
                                <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.25} />
                                {connected === 1 ? 'Connected' : `${connected} accounts`}
                            </>
                        )}
                    </span>
                ) : (
                    idle
                )
            }
            label={connected ? `${title}: open your ${connected === 1 ? 'account' : 'accounts'}` : `Connect ${title}`}
            onOpen={connected ? onManage : onConnect}
            testId={testId}
            trailing={
                <button
                    type="button"
                    onClick={(event) => {
                        event.stopPropagation();
                        onConnect();
                    }}
                    aria-label={connected ? `Connect another ${title} account` : `Connect ${title}`}
                    className={BUTTON_OUTLINE_SM}
                >
                    Connect
                </button>
            }
        />
    );
}
