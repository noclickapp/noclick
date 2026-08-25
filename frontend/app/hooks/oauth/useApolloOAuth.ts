// Apollo OAuth hook — standard popup flow via createOAuthHook factory.
import { createOAuthHook } from './createOAuthHook';

export const useApolloOAuth = createOAuthHook({
    provider: 'apollo',
    defaultScopes: [
        'read_user_profile',
        'people_match', 'people_bulk_match',
        'organizations_enrich', 'organizations_bulk_enrich', 'organizations_search', 'organization_read',
        'mixed_people_api_search', 'mixed_companies_search',
        'contacts_search', 'contact_read', 'contact_write', 'contact_update',
        'contacts_bulk_create', 'contacts_bulk_update',
        'contact_stages_list', 'contact_stages_update', 'contact_owners_update',
        'account_read', 'account_write', 'account_update', 'accounts_search',
        'account_bulk_create', 'account_stages_list', 'account_stages_update', 'account_owners_update',
        'opportunity_read', 'opportunity_write', 'opportunity_update', 'opportunities_list', 'opportunity_stages_list',
        'emailer_campaigns_search', 'emailer_campaigns_create', 'emailer_campaigns_update',
        'emailer_campaigns_add_contact_ids', 'emailer_campaigns_remove_or_stop_contact_ids',
        'emailer_schedules_list', 'emailer_messages_search',
        'tasks_create', 'tasks_list',
        'notes_list', 'users_list', 'tags_list',
        'custom_fields_list', 'custom_field_write',
        'lists_create', 'lists_update', 'lists_add_entities', 'lists_remove_entities',
        'organizations_job_posting', 'organizations_news_articles',
        'person_read',
    ],
});
