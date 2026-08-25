// API route for handling password reset requests
// Created specifically for the AuthModal popup on the landing page

import { type ActionFunctionArgs } from 'react-router';
import { json } from '~/lib/routerResponse';
import { authenticate } from '~/lib/auth.server';

export async function action({ request }: ActionFunctionArgs) {
    const formData = await request.formData();
    const email = formData.get('email') as string;

    if (!email) {
        return json({ error: 'Email is required' }, { status: 400 });
    }

    const { error, success, headers } = await authenticate(request, 'reset', { email });

    if (error) {
        return json({ error }, { status: 400, headers });
    }

    return json({ success }, { headers });
}