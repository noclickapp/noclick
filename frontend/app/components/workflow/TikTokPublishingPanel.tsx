// Creator-aware settings and media preview for TikTok direct-post workflows.
// Configuration remains reusable by unattended runs; this is not an approval dialog.
import { useId, useState } from 'react';
import { useTikTokCreator } from '~/hooks/useTikTokCreator';
import { tikTokDisclosureError } from '~/utils/tikTokPublishing';

export const TIKTOK_PANEL_FIELDS = new Set([
    'privacy_level',
    'disable_comment',
    'disable_duet',
    'disable_stitch',
    'disclose_commercial_content',
    'brand_content_toggle',
    'brand_organic_toggle',
    'is_aigc',
]);

function previewUrl(value: unknown): string | undefined {
    if (typeof value !== 'string' || value.includes('{{')) return;
    try {
        const url = new URL(value);
        if (url.protocol === 'https:' && !url.username && !url.password)
            return url.href;
    } catch {
        /* Upstream references and resource IDs are not preview URLs. */
    }
}

export function TikTokPublishingPanel({
    config,
    operation,
    credentialId,
    onChange,
}: {
    config: Record<string, unknown>;
    operation: string;
    credentialId: string;
    onChange: (key: string, value: string) => void;
}) {
    const id = useId();
    const [refresh, setRefresh] = useState(0);
    const { options, loading, error } = useTikTokCreator(credentialId, refresh);
    const creator = options[0]?.metadata;
    const video = operation === 'direct_post_video';
    const urls = video
        ? [previewUrl(config.video_url)]
        : String(config.photo_urls ?? '')
              .split(',')
              .map((url) => previewUrl(url.trim()));
    const paid = config.brand_content_toggle === 'true';
    const ownBrand = config.brand_organic_toggle === 'true';
    const commercial = config.disclose_commercial_content === 'true';
    const disclosureError = tikTokDisclosureError(config);
    const visibility =
        typeof config.privacy_level === 'string' ? config.privacy_level : '';
    const validVisibility = options.some(
        (option) => option.value === visibility
    );
    const checkbox = (
        key: string,
        label: string,
        checked: boolean,
        disabled = false,
        inverse = false
    ) => (
        <label
            key={key}
            className={`flex items-center gap-2 text-sm ${disabled ? 'text-muted-foreground' : ''}`}
        >
            <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(event) =>
                    onChange(
                        key,
                        String(
                            inverse
                                ? !event.target.checked
                                : event.target.checked
                        )
                    )
                }
            />
            {label}
        </label>
    );
    return (
        <section
            data-testid="tiktok-publishing-panel"
            aria-label="TikTok publishing settings"
            className="space-y-3 rounded-lg border border-border bg-card p-3"
        >
            <div className="flex items-center justify-between gap-2">
                <h3 className="font-medium">
                    Post to TikTok
                    {creator?.creator_nickname
                        ? ` · ${String(creator.creator_nickname)}`
                        : ''}
                </h3>
                <button
                    type="button"
                    disabled={loading || !credentialId}
                    onClick={() => setRefresh((value) => value + 1)}
                    className="text-xs underline"
                >
                    Refresh account
                </button>
            </div>
            {!credentialId && (
                <p className="text-sm text-muted-foreground">
                    Connect your TikTok account to load publishing options.
                </p>
            )}
            {loading && <p role="status">Loading current creator options…</p>}
            {error && <p role="alert">{error}</p>}
            {credentialId && !loading && !error && options.length === 0 && (
                <p role="alert">
                    TikTok has no available posting options for this account.
                    Publishing cannot proceed.
                </p>
            )}
            {video && Boolean(creator?.max_video_post_duration_sec) && (
                <p className="text-xs text-muted-foreground">
                    Maximum video duration:{' '}
                    {String(creator?.max_video_post_duration_sec)} seconds.
                </p>
            )}
            <div aria-label="Content preview" className="space-y-2">
                {urls.some(Boolean) ? (
                    urls.map(
                        (url, index) =>
                            url &&
                            (video ? (
                                <video
                                    key={url}
                                    src={url}
                                    controls
                                    preload="metadata"
                                    className="max-h-56 w-full rounded"
                                />
                            ) : (
                                <img
                                    key={`${url}-${index}`}
                                    src={url}
                                    alt={`Photo ${index + 1} preview`}
                                    className="max-h-40 rounded"
                                />
                            ))
                    )
                ) : (
                    <p className="text-xs text-muted-foreground">
                        Select media below to preview it. Upstream-generated
                        content is resolved when this workflow runs.
                    </p>
                )}
                {Boolean(config.title) && (
                    <p className="whitespace-pre-wrap text-sm">
                        {String(config.title)}
                    </p>
                )}
                {!video && Boolean(config.description) && (
                    <p className="whitespace-pre-wrap text-sm">
                        {String(config.description)}
                    </p>
                )}
            </div>
            <label htmlFor={`${id}-privacy`} className="block text-sm">
                Privacy
            </label>
            <select
                id={`${id}-privacy`}
                value={validVisibility ? visibility : ''}
                disabled={loading || !options.length}
                onChange={(event) =>
                    onChange('privacy_level', event.target.value)
                }
                className="w-full rounded border border-input bg-background p-2 text-sm"
            >
                <option value="" disabled>
                    Select visibility…
                </option>
                {options.map((option) => (
                    <option
                        key={option.value}
                        value={option.value}
                        disabled={paid && option.value === 'SELF_ONLY'}
                    >
                        {option.label}
                    </option>
                ))}
            </select>
            {visibility &&
                !loading &&
                options.length > 0 &&
                !validVisibility && (
                    <p role="alert">
                        The selected visibility is no longer available. Choose
                        another option.
                    </p>
                )}
            {(video ? ['comment', 'duet', 'stitch'] : ['comment']).map(
                (interaction) => {
                    const restricted =
                        creator?.[`${interaction}_disabled`] === true;
                    return checkbox(
                        `disable_${interaction}`,
                        `Allow ${interaction}${restricted ? ' (disabled by TikTok)' : ''}`,
                        !restricted &&
                            config[`disable_${interaction}`] === 'false',
                        loading || !creator || restricted,
                        true
                    );
                }
            )}
            <label className="flex items-center gap-2 text-sm">
                <input
                    type="checkbox"
                    checked={commercial}
                    onChange={(event) => {
                        onChange(
                            'disclose_commercial_content',
                            String(event.target.checked)
                        );
                        if (!event.target.checked) {
                            onChange('brand_content_toggle', 'false');
                            onChange('brand_organic_toggle', 'false');
                        }
                    }}
                />
                Disclose commercial content
            </label>
            {commercial &&
                checkbox(
                    'brand_organic_toggle',
                    'Promote your own brand',
                    ownBrand
                )}
            {commercial &&
                checkbox(
                    'brand_content_toggle',
                    'Paid partnership with another brand',
                    paid,
                    visibility === 'SELF_ONLY' && !paid
                )}
            {commercial && visibility === 'SELF_ONLY' && !paid && (
                <p className="text-xs text-muted-foreground">
                    Paid partnership is unavailable with private visibility.
                </p>
            )}
            {(paid || ownBrand) && (
                <p className="text-xs">
                    TikTok will label this{' '}
                    {paid ? 'Paid partnership' : 'Promotional content'}.
                </p>
            )}
            {disclosureError && <p role="alert">{disclosureError}</p>}
            {checkbox(
                'is_aigc',
                'AI-generated content',
                config.is_aigc === 'true'
            )}
            <p className="text-xs text-muted-foreground">
                By posting, you agree to TikTok’s{' '}
                <a
                    href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                >
                    Music Usage Confirmation
                </a>
                {paid && (
                    <>
                        {' '}
                        and{' '}
                        <a
                            href="https://www.tiktok.com/legal/page/global/bc-policy/en"
                            target="_blank"
                            rel="noreferrer"
                            className="underline"
                        >
                            Branded Content Policy
                        </a>
                    </>
                )}
                .
            </p>
            <p className="text-xs text-muted-foreground">
                Running or scheduling this workflow sends its configured content
                directly to the connected TikTok account, without an inbox
                confirmation. You can edit the caption and settings before
                enabling it. TikTok processing can take a few minutes; check the
                returned publish status before attempting another post.
            </p>
        </section>
    );
}
