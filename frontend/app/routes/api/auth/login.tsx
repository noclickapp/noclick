// API route for handling user login via email/password
// Created specifically for the AuthModal popup on the landing page

import { type ActionFunctionArgs } from 'react-router';
import { json } from '~/lib/routerResponse';
import { authenticate } from '~/lib/auth.server';

export async function action({ request }: ActionFunctionArgs) {
    const formData = await request.formData();
    const email = formData.get('email') as string;
    const password = formData.get('password') as string;
    const captchaToken = formData.get('captchaToken') as string;

    const { error, headers } = await authenticate(request, 'login', { email, password, captchaToken });

    if (error) {
        return json({ error }, { status: 400, headers });
    }

    return json({ redirectUrl: '/dashboard' }, { headers });
}