interface OAuthPostPopupOptions {
    action: string;
    name: string;
    fields: Record<string, string | undefined>;
    width?: number;
    height?: number;
}

/** Open an OAuth popup and submit sensitive setup values in a POST body. */
export function openOAuthPostPopup({
    action,
    name,
    fields,
    width = 500,
    height = 700,
}: OAuthPostPopupOptions): Window | null {
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;
    const target = `${name}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const popup = window.open(
        'about:blank',
        target,
        `width=${width},height=${height},left=${left},top=${top},popup=yes`
    );

    if (!popup) return null;

    const form = document.createElement('form');
    form.method = 'POST';
    form.action = action;
    form.target = target;
    form.hidden = true;

    for (const [fieldName, value] of Object.entries(fields)) {
        if (value === undefined) continue;
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = fieldName;
        input.value = value;
        form.appendChild(input);
    }

    document.body.appendChild(form);
    try {
        form.submit();
    } catch (error) {
        popup.close();
        throw error;
    } finally {
        form.remove();
    }

    return popup;
}

/** A sign-in page whose address arrives after an await: the tab is opened now, inside the click, and pointed at it
 *  once it's known. Opened after the await, browsers count it as a pop-up nobody asked for and block it, so the
 *  provide page's "Sign in with Claude" opened nothing (2026-11-12). */
export function openTabForLater(): { go: (url: string) => void; close: () => void } {
    const tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
    return {
        go: (url) => {
            if (tab && !tab.closed) tab.location.href = url;
            else window.open(url, '_blank', 'noopener,noreferrer');
        },
        close: () => {
            if (tab && !tab.closed) tab.close();
        },
    };
}
