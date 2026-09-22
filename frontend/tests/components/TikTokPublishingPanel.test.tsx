// @vitest-environment jsdom
// Exercise real publishing controls with a mocked credential-gated transport.
// No provider calls or posts are made by these regression tests.
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import { TikTokPublishingPanel } from '~/components/workflow/TikTokPublishingPanel';

const send = vi.hoisted(() => vi.fn());
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: send }));
vi.mock('~/types/socket-events.generated', () => ({
    WorkflowNodeLoadOptionsRequest: { create: (x: unknown) => x },
}));
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
});
const response = {
    success: true,
    options: [
        {
            value: 'SELF_ONLY',
            label: 'Only me',
            metadata: {
                creator_nickname: 'Review Creator',
                comment_disabled: true,
                max_video_post_duration_sec: 300,
            },
        },
        { value: 'PUBLIC_TO_EVERYONE', label: 'Public' },
    ],
};
function show(
    config: Record<string, unknown> = {},
    operation = 'direct_post_video'
) {
    send.mockResolvedValue(response);
    const onChange = vi.fn();
    const view = render(
        <TikTokPublishingPanel
            config={config}
            credentialId="test-credential"
            operation={operation}
            onChange={onChange}
        />
    );
    return { ...view, onChange };
}

describe('TikTok publishing controls', () => {
    it('loads the actual creator without selecting a privacy default', async () => {
        const { onChange } = show();
        await screen.findByText('Post to TikTok · Review Creator');
        expect(
            (screen.getByLabelText('Privacy') as HTMLSelectElement).value
        ).toBe('');
        expect(onChange).not.toHaveBeenCalled();
        expect(send.mock.calls[0][0]).toMatchObject({
            credential_id: 'test-credential',
            field_name: 'privacy_level',
        });
        fireEvent.change(screen.getByLabelText('Privacy'), {
            target: { value: 'SELF_ONLY' },
        });
        expect(onChange).toHaveBeenCalledWith('privacy_level', 'SELF_ONLY');
    });
    it('disables restricted interactions and keeps other interactions opt-in', async () => {
        const { onChange } = show({ disable_comment: 'false' });
        await screen.findByText('Post to TikTok · Review Creator');
        const comments = screen.getByLabelText(
            'Allow comment (disabled by TikTok)'
        ) as HTMLInputElement;
        expect(comments.disabled).toBe(true);
        expect(comments.checked).toBe(false);
        expect(
            (screen.getByLabelText('Allow duet') as HTMLInputElement).checked
        ).toBe(false);
        fireEvent.click(screen.getByLabelText('Allow duet'));
        expect(onChange).toHaveBeenCalledWith('disable_duet', 'false');
    });
    it('shows previews and commercial declarations without a run approval dialog', async () => {
        const { container } = show({
            video_url: 'https://media.example/video.mp4',
            title: 'Original video',
            privacy_level: 'SELF_ONLY',
            brand_content_toggle: 'true',
        });
        await screen.findByText('Post to TikTok · Review Creator');
        expect(container.querySelector('video')?.getAttribute('src')).toBe(
            'https://media.example/video.mp4'
        );
        expect(screen.getByText('Original video')).toBeTruthy();
        expect(
            screen.getByRole('link', { name: 'Branded Content Policy' })
        ).toBeTruthy();
        expect(screen.getByRole('alert').textContent).toContain(
            'cannot be private'
        );
        expect(screen.queryByRole('dialog')).toBeNull();
    });
    it('does not pretend unresolved automated content has been previewed', async () => {
        const { container } = show({ video_url: '{{ upstream.url }}' });
        await screen.findByText('Post to TikTok · Review Creator');
        expect(container.querySelector('video')).toBeNull();
        expect(
            screen.getByText(/Upstream-generated content is resolved/)
        ).toBeTruthy();
    });
    it('photo controls omit duet and stitch', async () => {
        show(
            {
                photo_urls:
                    'https://media.example/a.jpg,https://media.example/b.jpg',
            },
            'direct_post_photo'
        );
        await screen.findByText('Post to TikTok · Review Creator');
        expect(screen.queryByLabelText('Allow duet')).toBeNull();
        expect(screen.getAllByRole('img')).toHaveLength(2);
    });
    it('rejects stale creator responses after switching credentials', async () => {
        let finishFirst!: (value: unknown) => void;
        send.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finishFirst = resolve;
                })
        ).mockResolvedValueOnce({
            success: true,
            options: [
                {
                    value: 'SELF_ONLY',
                    label: 'Only me',
                    metadata: { creator_nickname: 'Second Creator' },
                },
            ],
        });
        const { rerender } = render(
            <TikTokPublishingPanel
                config={{}}
                credentialId="first"
                operation="direct_post_video"
                onChange={vi.fn()}
            />
        );
        rerender(
            <TikTokPublishingPanel
                config={{}}
                credentialId="second"
                operation="direct_post_video"
                onChange={vi.fn()}
            />
        );
        await screen.findByText('Post to TikTok · Second Creator');
        finishFirst(response);
        await waitFor(() =>
            expect(
                screen.queryByText('Post to TikTok · Review Creator')
            ).toBeNull()
        );
    });
    it('does not preview unsafe or credential-bearing URLs', async () => {
        const { container } = show({
            video_url: 'https://user:secret@media.example/v.mp4',
        });
        await screen.findByText('Post to TikTok · Review Creator');
        expect(container.querySelector('video')).toBeNull();
    });
});
