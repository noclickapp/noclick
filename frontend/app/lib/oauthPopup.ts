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
