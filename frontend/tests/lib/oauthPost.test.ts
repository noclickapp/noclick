import { describe, expect, it } from 'vitest';
import { oauthFormString, oauthPostFormData } from '~/lib/oauthPost.server';

function postRequest(origin?: string) {
    return new Request('https://app.example.test/api/auth/slack/authorize', {
        method: 'POST',
        headers: origin ? { Origin: origin } : undefined,
        body: new URLSearchParams({
            client_id: 'public-id',
            client_secret: 'private-value',
        }),
    });
}

describe('OAuth setup POST parsing', () => {
    it('accepts same-origin form fields without putting the secret in the URL', async () => {
        const request = postRequest('https://app.example.test');
        const formData = await oauthPostFormData(request);

        expect(request.url).not.toContain('private-value');
        expect(oauthFormString(formData, 'client_id')).toBe('public-id');
        expect(oauthFormString(formData, 'client_secret')).toBe(
            'private-value'
        );
    });

    it.each([undefined, 'https://attacker.example', 'not a URL'])(
        'rejects a missing or foreign Origin header: %s',
        async (origin) => {
            await expect(
                oauthPostFormData(postRequest(origin))
            ).rejects.toMatchObject({
                status: 403,
            });
        }
    );
});
