/**
 * Usage Dashboard Page Route
 *
 * Full-page usage dashboard accessible from /dashboard/usage
 * Shows comprehensive usage statistics, charts, and cost breakdowns.
 */

import { type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useLoaderData } from 'react-router';
import { requireAuth } from '~/lib/supabase';
import { UsagePage } from '~/components/usage/page/UsagePage';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Usage - NoClick',
        description: 'Your NoClick usage and billing breakdown.',
        indexable: false,
    });

export async function loader({ request }: LoaderFunctionArgs) {
  const { user, headers } = await requireAuth(request);

  return json({
    user,
    title: 'Usage Dashboard',
  }, { headers });
}

export default function UsageDashboardPage() {
  useLoaderData<JsonPayloadOf<typeof loader>>();

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-[1080px] px-4 py-8">
        <UsagePage />
      </div>
    </div>
  );
}
