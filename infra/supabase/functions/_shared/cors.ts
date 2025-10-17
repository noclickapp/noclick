// Shared CORS headers for Supabase Edge Functions
// Allows cross-origin requests from the frontend application

export const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}
