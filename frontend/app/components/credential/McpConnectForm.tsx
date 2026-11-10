// The connect form for an integration's own MCP server (credential kind `mcp`): one button that signs in through the
// vendor's MCP auth, or a key field when the server takes a bearer key instead. Presentational over useMcpConnect,
// whose transport the host injects: the in-app socket (AppConnect) or a provide link (CredentialMethodConnect), so
// both surfaces connect the same way.
import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import {
    useMcpConnect,
    type McpConnectedCredential,
} from '~/hooks/useMcpConnect';
import { SecretInput } from '~/components/workflow/SecretInput';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '~/components/shell/fields';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { cn } from '~/lib/utils';

const INLINE =
    'rounded-sm text-foreground underline-offset-4 transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export interface McpConnectFormProps {
    credentialType: string;
    /** The app, as a person names it ("Canva"). */
    app: string;
    /** The line under the button: what connecting through MCP gives and doesn't. */
    note?: string | null;
    /** The transport; the in-app socket when omitted. */
    sendEvent?: OAuthExchange;
    onConnected: (
        credential: McpConnectedCredential,
        verification: CredentialTestConnectionResponse | null
    ) => void;
}

export function McpConnectForm({
    credentialType,
    app,
    note,
    sendEvent,
    onConnected,
}: McpConnectFormProps) {
    const { stage, error, clearError, connect, submitKey, cancel } =
        useMcpConnect({ credentialType, sendEvent, onConnected });
    const [key, setKey] = useState('');
    const waiting = stage !== 'idle' && stage !== 'key';
    const waitingLabel =
        stage === 'finishing'
            ? `Checking with ${app}…`
            : stage === 'starting'
              ? `Opening ${app}…`
              : `Waiting for ${app}…`;

    return (
        <div className="space-y-3" data-testid="mcp-connect">
            {error && (
                <div role="alert" className="text-[13px] leading-relaxed">
                    <p className="font-medium text-red-600 dark:text-red-400">{`Couldn’t connect ${app}`}</p>
                    <p className="mt-1 text-foreground/80">{error}</p>
                    <button
                        type="button"
                        onClick={clearError}
                        className={cn(QUIET_LINK, 'mt-1.5')}
                    >
                        Dismiss
                    </button>
                </div>
            )}
            {stage === 'key' ? (
                <form
                    className="space-y-3"
                    onSubmit={(event) => {
                        event.preventDefault();
                        if (key.trim()) void submitKey(key.trim());
                    }}
                >
                    <label className="block">
                        <span className={FIELD_LABEL}>{`${app} key`}</span>
                        <SecretInput
                            value={key}
                            onChange={(event) => setKey(event.target.value)}
                            placeholder={`The key ${app} gave you`}
                            inputClassName={FIELD}
                            autoComplete="off"
                        />
                    </label>
                    <button
                        type="submit"
                        disabled={!key.trim()}
                        className={cn(
                            BUTTON_PRIMARY,
                            'h-10 w-full justify-center'
                        )}
                    >
                        Connect
                    </button>
                </form>
            ) : (
                <button
                    type="button"
                    onClick={() => void connect()}
                    disabled={waiting}
                    aria-busy={waiting || undefined}
                    className={cn(
                        BUTTON_PRIMARY,
                        'h-10 w-full justify-center',
                        waiting && 'cursor-wait disabled:opacity-100'
                    )}
                >
                    {waiting ? (
                        <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            {waitingLabel}
                        </>
                    ) : (
                        `Continue with ${app}`
                    )}
                </button>
            )}
            {stage === 'signing_in' ? (
                <p className="text-[12.5px] leading-snug text-muted-foreground">
                    Finish in the {app} window.{' '}
                    <button type="button" onClick={cancel} className={INLINE}>
                        Cancel
                    </button>
                </p>
            ) : (
                note &&
                !waiting && (
                    <p className="text-[12.5px] leading-snug text-muted-foreground">
                        {note}
                    </p>
                )
            )}
        </div>
    );
}
