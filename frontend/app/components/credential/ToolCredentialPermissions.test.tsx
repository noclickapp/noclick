// @vitest-environment jsdom
// Exercise the real tool picker with route-backed credential policies.
// Approval changes must preserve the operation allowlist, other restrictions,
// owner boundaries, CSRF, and revision checks when credentials change.
import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AgentToolOperationsPicker } from '~/components/workflow/AgentToolOperationsPicker';
import type { CredentialPolicyState } from './CredentialPermissions';

const NativeRequest = Request;
beforeEach(() => {
    vi.stubGlobal(
        'Request',
        class extends NativeRequest {
            constructor(input: RequestInfo | URL, init?: RequestInit) {
                const options = { ...init, signal: undefined };
                if (init?.body instanceof URLSearchParams) {
                    options.body = init.body.toString();
                    options.headers = {
                        'Content-Type':
                            'application/x-www-form-urlencoded;charset=UTF-8',
                    };
                }
                super(input, options);
            }
        }
    );
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const sendKey = 'automation-gmail.send_email_message';
const base: CredentialPolicyState = {
    id: 'personal',
    name: 'Personal email',
    can_edit: true,
    revision: 5,
    approval_operations: ['retired.action', 'other-provider.write'],
    operations: [
        {
            key: sendKey,
            operation: 'send_email_message',
            node_type: 'automation-gmail',
            display_name: 'Send Email Message',
            description: '',
        },
    ],
};
function mount(
    options: {
        state?: CredentialPolicyState;
        conflict?: boolean;
        denied?: boolean;
        readonly?: boolean;
        saveDelay?: Promise<void>;
    } = {}
) {
    const onChange = vi.fn();
    const submitted: {
        id: string;
        csrf: unknown;
        payload: { operations: string[]; expected_revision: number };
    }[] = [];
    let current = options.state ?? base;
    const loader = vi.fn(
        ({ params }: { params: Record<string, string | undefined> }) => ({
            state: options.denied
                ? { detail: 'Credential not accessible.' }
                : params.credentialId === 'work'
                  ? {
                        ...base,
                        id: 'work',
                        name: 'Work email',
                        approval_operations: [sendKey],
                    }
                  : current,
            csrfToken: `csrf-${params.credentialId}`,
        })
    );
    const action = vi.fn(
        async ({
            request,
            params,
        }: {
            request: Request;
            params: Record<string, string | undefined>;
        }) => {
            const form = await request.formData();
            const payload = JSON.parse(String(form.get('payload')));
            submitted.push({
                id: params.credentialId!,
                csrf: form.get('csrf_token'),
                payload,
            });
            if (options.saveDelay) await options.saveDelay;
            if (options.conflict) {
                current = {
                    ...current,
                    revision: 6,
                    approval_operations: [sendKey, 'other-provider.new-rule'],
                };
                return { error: 'The policy changed. Refresh before saving.' };
            }
            current = {
                ...current,
                revision: current.revision + 1,
                approval_operations: payload.operations,
            };
            return { saved: true };
        }
    );
    function Host() {
        const [id, setId] = useState('personal');
        return (
            <>
                <button onClick={() => setId('work')}>Switch credential</button>
                <AgentToolOperationsPicker
                    nodeType="automation-gmail"
                    credentialIds={
                        options.readonly
                            ? undefined
                            : { google: id, credential_type: 'google' }
                    }
                    selectedOperations={['send_email_message']}
                    onChange={onChange}
                />
            </>
        );
    }
    const router = createMemoryRouter([
        { path: '/', element: <Host /> },
        { path: '/credential/permissions/:credentialId', loader, action },
    ]);
    render(<RouterProvider router={router} />);
    return { onChange, loader, action, submitted, router };
}
const lock = () =>
    screen.getByRole('button', {
        name: 'Require approval for Send Email Message',
    });
async function ready() {
    await screen.findByRole('button', {
        name: 'Require approval for Send Email Message',
    });
    await waitFor(() =>
        expect(lock().getAttribute('aria-disabled')).not.toBe('true')
    );
}

it('locks and unlocks the bound credential without changing tool selection or other rules', async () => {
    const { onChange, submitted, action, router, loader } = mount();
    await ready();
    expect(lock().textContent).toBe('');
    expect(action).not.toHaveBeenCalled();
    fireEvent.click(lock());
    await waitFor(() =>
        expect(lock().getAttribute('aria-pressed')).toBe('true')
    );
    await ready();
    expect(submitted[0]).toEqual({
        id: 'personal',
        csrf: 'csrf-personal',
        payload: {
            operations: [...base.approval_operations, sendKey],
            expected_revision: 5,
        },
    });
    expect(onChange).not.toHaveBeenCalled();
    await ready();
    fireEvent.click(lock());
    await waitFor(() =>
        expect(lock().getAttribute('aria-pressed')).toBe('false')
    );
    await ready();
    expect(submitted[1].payload).toEqual({
        operations: base.approval_operations,
        expected_revision: 6,
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(router.state.location.pathname).toBe('/');
    fireEvent.click(
        screen.getByRole('checkbox', {
            name: 'Allow Send Email Message',
        })
    );
    expect(onChange).toHaveBeenCalledWith([]);
    expect(action).toHaveBeenCalledTimes(2);
    expect(loader).toHaveBeenCalledTimes(3);
});

it('transitions immediately without replacing the icons and ignores duplicate clicks while saving', async () => {
    let finish!: () => void;
    const saveDelay = new Promise<void>((resolve) => {
        finish = resolve;
    });
    const { action, loader } = mount({ saveDelay });
    try {
        await ready();
        const button = lock();
        const icons = [...button.querySelectorAll('svg')];
        expect(icons).toHaveLength(2);
        fireEvent.click(button);
        expect(button.getAttribute('aria-pressed')).toBe('true');
        expect(button.getAttribute('aria-busy')).toBe('true');
        expect((button as HTMLButtonElement).disabled).toBe(false);
        expect([...button.querySelectorAll('svg')]).toEqual(icons);
        fireEvent.click(button);
        await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
        finish();
        await ready();
        expect(lock()).toBe(button);
        expect([...button.querySelectorAll('svg')]).toEqual(icons);
        expect(loader).toHaveBeenCalledTimes(2);
    } finally {
        finish();
    }
});

it('reloads a conflicting policy without retrying an unlock or overwriting newer rules', async () => {
    const { action } = mount({
        state: { ...base, approval_operations: [sendKey] },
        conflict: true,
    });
    await ready();
    fireEvent.click(lock());
    expect((await screen.findByRole('alert')).textContent).toContain(
        'policy changed'
    );
    await ready();
    expect(lock().getAttribute('aria-pressed')).toBe('true');
    expect(action).toHaveBeenCalledTimes(1);
});

it.each([
    { name: 'shared connection', state: { ...base, can_edit: false } },
    {
        name: 'all-tools policy',
        state: { ...base, approval_operations: ['*'] },
    },
])(
    'does not relax the $name through an individual toggle',
    async ({ state }) => {
        const { action } = mount({ state });
        const button = await screen.findByRole('button', {
            name: 'Require approval for Send Email Message',
        });
        expect((button as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(button);
        expect(action).not.toHaveBeenCalled();
    }
);

it('loads the new connection when the node changes credentials', async () => {
    const { submitted } = mount();
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Switch credential' }));
    await screen.findByText('Work email');
    await ready();
    expect(lock().getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(lock());
    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].id).toBe('work');
    expect(submitted[0].csrf).toBe('csrf-work');
});

it('shows access errors without editable locks', async () => {
    mount({ denied: true });
    expect((await screen.findByRole('alert')).textContent).toBe(
        'Credential not accessible.'
    );
    expect(
        screen.queryByRole('button', { name: /Require approval/ })
    ).toBeNull();
});

it('does not load editable policies for read-only picker hosts', () => {
    const { loader } = mount({ readonly: true });
    expect(loader).not.toHaveBeenCalled();
    expect(screen.queryByText('Approval rules')).toBeNull();
});
