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
import { UsageDashboard } from '~/components/usage/UsageDashboard';
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
  const { title } = useLoaderData<JsonPayloadOf<typeof loader>>();

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-8 max-w-7xl">
        <UsageDashboard />
      </div>
    </div>
  );
}
