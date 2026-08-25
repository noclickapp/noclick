// API route for handling user registration
// Created specifically for the AuthModal popup on the landing page

import { type ActionFunctionArgs } from 'react-router';
import { json } from '~/lib/routerResponse';
import { authenticate } from '~/lib/auth.server';

export async function action({ request }: ActionFunctionArgs) {
    const formData = await request.formData();
    const email = formData.get('email') as string;
    const password = formData.get('password') as string;
    const confirmPassword = formData.get('confirmPassword') as string;
    const username = formData.get('username') as string | null;
    const captchaToken = formData.get('captchaToken') as string;

    const { error, success, headers } = await authenticate(request, 'register', {
        email,
        password,
        confirmPassword,
        captchaToken,
        ...(username && { username })
    });

    if (error) {
        return json({ error }, { status: 400, headers });
    }

    return json({ success }, { headers });
}