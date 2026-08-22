// @vitest-environment jsdom

import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    sendEventAsync: vi.fn(),
    uploadFile: vi.fn(),
    writeText: vi.fn(),
}));

vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: (...args: unknown[]) => mocks.sendEventAsync(...args),
}));

vi.mock('~/hooks/useResourceUpload', () => ({
    useResourceUpload: () => ({
        uploadFile: mocks.uploadFile,
        uploading: false,
        progress: null,
    }),
}));

vi.mock('~/components/workflow/WorkflowContext', () => ({
    useWorkflowId: () => 'workflow-1',
}));

import { FileUploadBlock } from '~/components/interface/blocks/FileUploadBlock';

const RESOURCE_ID = '12345678-1234-1234-1234-1234567890ab';

function renderBlock() {
    return render(
        <FileUploadBlock
            id="upload-node"
            config={{ resource_ids: RESOURCE_ID }}
            isSelected={false}
            onConfigChange={() => {}}
        />
    );
}

function mockResource(
    downloadUrl: string,
    storageRef: string | null = 'private/object.pdf'
) {
    mocks.sendEventAsync.mockImplementation(
        async (request: { event_name: string }) => {
            if (request.event_name === 'resource:get') {
                return {
                    resource: {
                        name: 'review.pdf',
                        size_bytes: 2048,
                        storage_ref: storageRef,
                    },
                };
            }
            if (request.event_name === 'resource:download_url') {
                return { download_url: downloadUrl };
            }
            throw new Error(`Unexpected event: ${request.event_name}`);
        }
    );
}

describe('FileUploadBlock copy link', () => {
    beforeEach(() => {
        mocks.sendEventAsync.mockReset();
        mocks.uploadFile.mockReset();
        mocks.writeText.mockReset().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: { writeText: mocks.writeText },
        });
    });

    afterEach(cleanup);

    it('requests a fresh authenticated URL when a private resource link is copied', async () => {
        const signedUrl =
            'http://minio:9000/workflow-resources/private/object.pdf?X-Amz-Signature=fresh';
        mockResource(signedUrl);
        renderBlock();

        const copy = await screen.findByRole('button', {
            name: 'Copy link to review.pdf',
        });
        expect(
            mocks.sendEventAsync.mock.calls.some(
                ([request]) => request.event_name === 'resource:download_url'
            )
        ).toBe(false);

        fireEvent.click(copy);

        await waitFor(() =>
            expect(mocks.writeText).toHaveBeenCalledWith(signedUrl)
        );
        expect(mocks.sendEventAsync).toHaveBeenCalledWith({
            event_name: 'resource:download_url',
            resource_id: RESOURCE_ID,
        });
        expect(copy.getAttribute('title')).toBe('Copied');
    });

    it('copies the permanent CDN URL selected by the backend without reconstructing storage_ref', async () => {
        const permanentUrl =
            'https://cdn.example.test/files/permanent-review-link';
        mockResource(permanentUrl, 'owner/workflow/internal-object-key.pdf');
        renderBlock();

        fireEvent.click(
            await screen.findByRole('button', {
                name: 'Copy link to review.pdf',
            })
        );

        await waitFor(() =>
            expect(mocks.writeText).toHaveBeenCalledWith(permanentUrl)
        );
        expect(mocks.writeText).not.toHaveBeenCalledWith(
            expect.stringContaining('internal-object-key.pdf')
        );
    });

    it('renews the link for a newly uploaded private resource instead of caching its first signed URL', async () => {
        const firstSignedUrl =
            'http://minio:9000/workflow-resources/private/new.pdf?X-Amz-Signature=first';
        const freshSignedUrl =
            'http://minio:9000/workflow-resources/private/new.pdf?X-Amz-Signature=fresh';
        mocks.uploadFile.mockResolvedValue({
            resourceId: RESOURCE_ID,
            publicUrl: firstSignedUrl,
            name: 'new.pdf',
            mimeType: 'application/pdf',
            sizeBytes: 42,
        });
        mocks.sendEventAsync.mockResolvedValue({
            download_url: freshSignedUrl,
        });
        const { container } = render(
            <FileUploadBlock
                id="upload-node"
                config={{}}
                isSelected={false}
                onConfigChange={() => {}}
            />
        );

        const input = container.querySelector('input[type="file"]');
        expect(input).toBeTruthy();
        fireEvent.change(input!, {
            target: {
                files: [
                    new File(['contents'], 'new.pdf', {
                        type: 'application/pdf',
                    }),
                ],
            },
        });

        fireEvent.click(
            await screen.findByRole('button', { name: 'Copy link to new.pdf' })
        );
        await waitFor(() =>
            expect(mocks.writeText).toHaveBeenCalledWith(freshSignedUrl)
        );
        expect(mocks.writeText).not.toHaveBeenCalledWith(firstSignedUrl);
    });

    it('does not offer a copy action when the resource has no stored blob', async () => {
        mockResource('https://unused.example.test', null);
        renderBlock();

        expect(await screen.findByText('review.pdf')).toBeTruthy();
        expect(
            screen.queryByRole('button', { name: /Copy link to/ })
        ).toBeNull();
        expect(
            mocks.sendEventAsync.mock.calls.some(
                ([request]) => request.event_name === 'resource:download_url'
            )
        ).toBe(false);
    });
});
