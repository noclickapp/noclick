"""Texting the account assistant: WhatsApp (Meta's Cloud API) and iMessage (a Sendblue line) carry a person's texts
into the same coordinator conversation the web chat shows, and its replies back. ``channel`` is the rule for a text,
``whatsapp`` and ``imessage`` the transports, ``routes`` their webhooks, ``owner_message`` how the assistant reaches its
owner's phone on its own."""
