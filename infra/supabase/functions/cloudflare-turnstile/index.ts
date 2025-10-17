// Cloudflare Turnstile CAPTCHA verification Edge Function
// Verifies CAPTCHA tokens from the frontend before allowing auth operations

import { corsHeaders } from '../_shared/cors.ts'

console.log('Cloudflare Turnstile verification function initialized')

function ips(req: Request) {
  return req.headers.get('x-forwarded-for')?.split(/\s*,\s*/)
}

Deno.serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    const { token } = await req.json()

    if (!token) {
      return new Response(
        JSON.stringify({ success: false, error: 'No token provided' }),
        {
          status: 400,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    const clientIps = ips(req) || ['']
    const ip = clientIps[0]

    // Validate the token by calling Cloudflare's siteverify API
    const formData = new FormData()
    formData.append('secret', Deno.env.get('CLOUDFLARE_SECRET_KEY') ?? '')
    formData.append('response', token)
    formData.append('remoteip', ip)

    const url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
    const result = await fetch(url, {
      body: formData,
      method: 'POST',
    })

    const outcome = await result.json()
    console.log('Turnstile verification outcome:', outcome)

    if (outcome.success) {
      return new Response(
        JSON.stringify({ success: true }),
        {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    return new Response(
      JSON.stringify({
        success: false,
        error: 'CAPTCHA verification failed',
        'error-codes': outcome['error-codes']
      }),
      {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      }
    )
  } catch (error) {
    console.error('Error verifying turnstile token:', error)
    return new Response(
      JSON.stringify({
        success: false,
        error: 'Internal server error during verification'
      }),
      {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      }
    )
  }
})
