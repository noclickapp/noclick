// @vitest-environment jsdom
// The dashboard's onboarding gate as the page loads: the server renders it from the token's claim alone, and the
// browser hydrates that HTML knowing more (an earlier onboarding's marker, a pending invite or agent setup). Deciding in
// the first render drew the questionnaire on the server and the dashboard in the browser, and React threw the server's
// page away ("Hydration failed", 2026-10-21).
import { act } from '@testing-library/react';
import { hydrateRoot } from 'react-dom/client';
import { renderToString } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useOnboardingGate } from '~/hooks/useOnboardingGate';
import { markOnboardingPersisted } from '~/lib/onboardingLocal';

function Gate({ claimed }: { claimed: boolean }) {
    const { gate } = useOnboardingGate('user-1', claimed, () => {});
    return <p>{gate}</p>;
}

// The server's HTML (rendered before this browser's storage is set up, as the server never sees it), hydrated here.
async function load(claimed: boolean, browserKnows: () => void) {
    const html = renderToString(<Gate claimed={claimed} />);
    browserKnows();
    const container = document.createElement('div');
    container.innerHTML = html;
    document.body.appendChild(container);
    const onRecoverableError = vi.fn();
    await act(async () => {
        hydrateRoot(container, <Gate claimed={claimed} />, {
            onRecoverableError,
        });
    });
    return { html, container, onRecoverableError };
}

afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    document.body.innerHTML = '';
});

describe('the onboarding gate on a page load', () => {
    it('waits on the server, then lets an earlier onboarding through without a hydration error', async () => {
        const { html, container, onRecoverableError } = await load(false, () =>
            markOnboardingPersisted('user-1')
        );
        expect(html).toContain('pending');
        expect(onRecoverableError).not.toHaveBeenCalled();
        expect(container.textContent).toBe('dashboard');
    });

    it('lets an agent being set up through the same way', async () => {
        const { container, onRecoverableError } = await load(false, () =>
            sessionStorage.setItem('noclick_scaffold_workflow_data', '{}')
        );
        expect(onRecoverableError).not.toHaveBeenCalled();
        expect(container.textContent).toBe('dashboard');
    });

    it('asks once hydrated when nothing says otherwise', async () => {
        const { container, onRecoverableError } = await load(false, () => {});
        expect(onRecoverableError).not.toHaveBeenCalled();
        expect(container.textContent).toBe('questionnaire');
    });

    it('opens the dashboard from the first render when the token says onboarded', async () => {
        const { html, container } = await load(true, () => {});
        expect(html).toContain('dashboard');
        expect(container.textContent).toBe('dashboard');
    });
});
