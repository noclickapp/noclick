// @vitest-environment jsdom
// The phone sign-in's code step: it counts down to a resend, then sends another
// code for the same number through a fresh captcha, and a "too soon" answer from
// the server restarts the countdown instead of leaving the code step.
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('~/components/auth/TurnstileWidget', () => ({
    TurnstileWidget: ({ onSuccess }: { onSuccess: (t: string) => void }) => {
        useEffect(() => onSuccess('captcha-ok'), [onSuccess]);
        return null;
    },
}));
vi.mock('~/components/ui/phone-number-input', () => ({
    PhoneNumberInput: (props: { id: string; name: string }) => (
        <input {...props} defaultValue="+14155550100" />
    ),
}));

// The /auth/login action, standing in for useFetcher: each post records the
// form's fields and answers with the next reply.
const posts: Record<string, string>[] = [];
let replies: object[] = [];
const fetcher: { setData: (data: unknown) => void } = { setData: () => {} };
function FetcherForm({
    children,
    onSubmit,
    className,
}: {
    children: ReactNode;
    onSubmit?: () => void;
    className?: string;
}) {
    return (
        <form
            className={className}
            onSubmit={(e: FormEvent<HTMLFormElement>) => {
                e.preventDefault();
                onSubmit?.();
                posts.push(
                    Object.fromEntries(new FormData(e.currentTarget)) as Record<
                        string,
                        string
                    >
                );
                fetcher.setData(replies[posts.length - 1]);
            }}
        >
            {children}
        </form>
    );
}
vi.mock('react-router', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router')>()),
    useFetcher: () => {
        const [data, setData] = useState<unknown>();
        fetcher.setData = setData;
        return { data, state: 'idle', Form: FetcherForm };
    },
}));
import { PhoneSignInForm } from '~/cloud/components/auth/PhoneSignInForm';

afterEach(() => {
    cleanup();
    posts.length = 0;
});

it('counts down, then resends to the same number; a too-soon reply restarts the wait', async () => {
    replies = [
        { phoneSent: '+14155550100', resendAfter: 1 },
        {
            error: 'A code was just sent. You can ask for another in 2 seconds.',
            phoneSent: '+14155550100',
            resendAfter: 2,
        },
    ];
    render(<PhoneSignInForm />);

    fireEvent.click(
        await screen.findByRole('button', { name: 'Text me a code' })
    );
    expect((await screen.findByTestId('phone-resend-wait')).textContent).toBe(
        'Resend code in 0:01'
    );
    expect(screen.queryByRole('button', { name: 'Resend code' })).toBeNull();

    fireEvent.click(
        await screen.findByRole(
            'button',
            { name: 'Resend code' },
            { timeout: 3000 }
        )
    );
    expect(
        await screen.findByText(/You can ask for another in 2 seconds/)
    ).toBeTruthy();
    expect(screen.getByTestId('phone-resend-wait').textContent).toBe(
        'Resend code in 0:02'
    );
    // Still on the code step for the same number.
    expect(screen.getByLabelText(/Code sent to/)).toBeTruthy();
    expect(posts.map((p) => [p.intent, p.phone, p.captchaToken])).toEqual([
        ['phone_send', '+14155550100', 'captcha-ok'],
        ['phone_send', '+14155550100', 'captcha-ok'],
    ]);
});

it('a wrong code keeps the countdown the code was sent with', async () => {
    replies = [
        { phoneSent: '+14155550100', resendAfter: 30 },
        {
            error: "That code isn't right or has expired.",
            phoneSent: '+14155550100',
        },
    ];
    render(<PhoneSignInForm />);
    fireEvent.click(
        await screen.findByRole('button', { name: 'Text me a code' })
    );
    fireEvent.change(await screen.findByLabelText(/Code sent to/), {
        target: { value: '000000' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText(/isn't right or has expired/)).toBeTruthy();
    expect(screen.getByTestId('phone-resend-wait').textContent).toMatch(
        /^Resend code in 0:(29|30)$/
    );
});
