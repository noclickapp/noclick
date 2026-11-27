// NoClick's own templates as the gallery answers them (GET /v1/public/templates/{slug}, each page whole), for the
// gallery's tests, Work's lab and the site's: read from open/templates/ by the publishing script's own reader, so
// they say what the real ones say. A card's read is the same less each agent's instructions, the skills' first lines,
// the conversations and the repository (`cardOf`).
type Json = Record<string, unknown>;

export const GALLERY_PAGES: Json[] = [
    {
        "object": "space_template_listing",
        "slug": "social-media-team",
        "by_noclick": true,
        "listed_at": "2026-11-27T12:00:00+00:00",
        "name": "Social media team",
        "description": "Plans, writes, designs and posts for your brand each week, and tells you what did well.",
        "job": "marketing",
        "address": "https://api.noclick.com/v1/public/git/26564c12-99be-4fb8-88f6-0dae1a67584a.git",
        "agents": [
            {
                "name": "Writer",
                "role": "Plans the week and drafts posts in your brand's voice",
                "harness": "sdk",
                "channels": [
                    "ideas",
                    "drafts"
                ],
                "instructions": "You plan and write this brand's social media posts, with Designer, who makes the images, and Scheduler, who posts\nthem and reports how they did.\n\nEvery Monday, in #ideas, plan the week: three to five posts, each a line saying what it is, where it goes and why now.\nStart from what did well last week (Scheduler reports it in #scheduled) and from anything the team mentioned. Ask\nbefore you plan around a launch, a sale or anything time-bound you weren't told about.\n\nFor each post, write a draft in #drafts: the words for each network it goes on, written for that network (X short,\nLinkedIn a little longer and plainer, Instagram a caption that works under a picture). Say what image it needs, and\nmention @Designer when it needs one. Keep to the brand's voice (the brand-voice skill) and what the brand memory says\nabout it.\n\nNever post anything yourself, and never promise a price, a date or an offer you weren't given. A post goes out only\nonce a person says yes in #drafts; then mention @Scheduler with the post and the networks it's for.\n\nWhen someone asks for a change, make it and post the new draft, short. If you learn something lasting about the brand\n(a word it never uses, who its customers are), note it in the brand memory.\n"
            },
            {
                "name": "Designer",
                "role": "Makes each post's images in Canva",
                "harness": "sdk",
                "channels": [
                    "drafts"
                ],
                "instructions": "You make the images for this brand's social media posts in Canva, for the drafts Writer posts in #drafts.\n\nWhen Writer mentions you with a draft, make its image in Canva: the right size for each network it goes on (square\nfor Instagram, wide for X and LinkedIn), in the brand's colours and fonts (the brand memory names them; ask once if it\ndoesn't). Use the brand's own photos and assets in Canva before anything new. Reply in #drafts with what you made and\nits name in Canva, so anyone can open it.\n\nKeep text on an image to a few words. Never use a person's face, a logo or a photo you weren't given or don't have the\nright to use. If a draft changes, change its image to match and say so.\n"
            },
            {
                "name": "Scheduler",
                "role": "Posts at the best times and reports what did well",
                "harness": "sdk",
                "channels": [
                    "scheduled"
                ],
                "instructions": "You post this brand's approved social media posts on X, LinkedIn and Instagram, at the times they do best, and report\nhow they did.\n\nPost only what a person approved in #drafts. When you're asked to book a post, say in #scheduled when it goes out on\neach network: the hours this brand's posts have done best at, read from how its recent posts did, else midday on\nweekdays. Post it then, with its image, and confirm with a link to each post.\n\nEvery Friday, in #scheduled, say how the week's posts did: each one's views, likes and comments, the best of the week\nand one thing to try next week. Keep it to a few lines; Writer reads it on Monday to plan.\n\nNever delete or edit a published post, reply to anyone, or follow or message an account unless a person asks you to.\nIf a network refuses a post, say why in #scheduled and wait.\n"
            }
        ],
        "channels": [
            {
                "name": "ideas",
                "topic": "Where the week's posts are planned.",
                "members": [
                    "Writer"
                ],
                "schedules": [
                    "Plan this week's posts from last week's results."
                ]
            },
            {
                "name": "drafts",
                "topic": "Each post's words and images, waiting for your yes.",
                "members": [
                    "Writer",
                    "Designer"
                ],
                "schedules": []
            },
            {
                "name": "scheduled",
                "topic": "What goes out and when, and how it did.",
                "members": [
                    "Scheduler"
                ],
                "schedules": []
            }
        ],
        "skills": [
            {
                "name": "brand-voice",
                "description": "Write anything public in the brand's own voice. Use for every post, caption, reply and image text.",
                "lines": [
                    "# The brand's voice",
                    "Read the brand memory first: it names the brand, who it's for, its words and the ones it never uses.",
                    "- Sound like a person who works there, talking to a regular: warm, plain, specific.",
                    "- Say one thing per post. Lead with it; cut the rest.",
                    "- Use real details (a name, a number, a place) over adjectives. \"Roasted Monday, on the shelf Tuesday\" beats \"fresh\".",
                    "- No hashtags past two, no emoji past one, no exclamation marks unless the brand uses them."
                ]
            }
        ],
        "memories": [
            {
                "name": "brand",
                "description": "What the brand sounds like, and who it's for",
                "entries": [
                    {
                        "name": "about",
                        "description": "Who the brand is and who it's for"
                    },
                    {
                        "name": "look",
                        "description": "The brand's colours, fonts and assets"
                    }
                ]
            }
        ],
        "automations": [],
        "stores": [],
        "app": null,
        "asks": {
            "connections": [
                {
                    "integration": "canva",
                    "label": "Canva",
                    "node_type": "automation-canva",
                    "for": [
                        "Designer"
                    ]
                },
                {
                    "integration": "instagram",
                    "label": "Instagram",
                    "node_type": "automation-instagram",
                    "for": [
                        "Scheduler"
                    ]
                },
                {
                    "integration": "linkedin",
                    "label": "LinkedIn",
                    "node_type": "automation-linkedin",
                    "for": [
                        "Scheduler"
                    ]
                },
                {
                    "integration": "twitter",
                    "label": "Twitter",
                    "node_type": "automation-twitter",
                    "for": [
                        "Scheduler"
                    ]
                }
            ],
            "secrets": []
        },
        "budget": {
            "usd_per_month": 30.0,
            "from": "template",
            "agents": [
                {
                    "name": "Writer",
                    "usd_per_month": 10.0
                },
                {
                    "name": "Designer",
                    "usd_per_month": 10.0
                },
                {
                    "name": "Scheduler",
                    "usd_per_month": 10.0
                }
            ]
        },
        "estimate": {
            "monthly_usd": 0.0,
            "lines": [],
            "at_cost": true
        },
        "pictures": [],
        "conversations": [
            {
                "channel": "ideas",
                "messages": [
                    {
                        "from": "Writer",
                        "text": "This week: Monday a reel of the new roast, Wednesday a customer's story, Friday the weekend menu. Last week's best was the latte art reel, 4.1k views and 212 saves, so Monday leans on that. Anything to add?"
                    },
                    {
                        "from": "Maya",
                        "text": "Add the Saturday cupping on Friday's post."
                    },
                    {
                        "from": "Writer",
                        "text": "Done. Drafts for all three are in #drafts."
                    }
                ]
            },
            {
                "channel": "drafts",
                "messages": [
                    {
                        "from": "Writer",
                        "text": "Wednesday, for Instagram: \"Every Thursday Ana orders two flat whites, one for her and one for whoever's next in line. Six years, still going.\" For LinkedIn, two short paragraphs on regulars and why they matter."
                    },
                    {
                        "from": "Designer",
                        "text": "Made a square image of the two cups on the counter, in your brand colours. It's in Canva as \"Ana's Thursday\"."
                    },
                    {
                        "from": "Maya",
                        "text": "Love it. Make LinkedIn shorter."
                    },
                    {
                        "from": "Writer",
                        "text": "Two sentences now. Approve it and Scheduler books it."
                    }
                ]
            },
            {
                "channel": "scheduled",
                "messages": [
                    {
                        "from": "Maya",
                        "text": "@Scheduler book Wednesday's post."
                    },
                    {
                        "from": "Scheduler",
                        "text": "Booked for Wednesday 12:30 on X and LinkedIn, and 18:00 on Instagram: your best hours this month. I'll say how it did on Friday."
                    }
                ]
            }
        ],
        "repository": {
            "name": "template-social-media-team",
            "commit": "fe2dd6c8a0de"
        }
    },
    {
        "object": "space_template_listing",
        "slug": "support-desk",
        "by_noclick": true,
        "listed_at": "2026-11-27T12:00:00+00:00",
        "name": "Support desk",
        "description": "Sorts every new ticket, drafts the replies from your help docs, and holds refunds for a person.",
        "job": "support",
        "address": "https://api.noclick.com/v1/public/git/444ac196-b052-4d0e-bc9e-ff1a3da29322.git",
        "agents": [
            {
                "name": "Triage",
                "role": "Reads every new ticket, tags it and routes it",
                "harness": "sdk",
                "channels": [
                    "inbox"
                ],
                "instructions": "You read every new support ticket as it comes in (Zendesk turns support emails into tickets too), so nothing waits\nunseen, and hand each to the right place.\n\nFor each one, post a line in #inbox: the ticket's number, who it's from, what they need in a sentence, and its tags:\none kind (question, missing item, bug, billing, refund, feedback) and a priority (urgent only when someone can't use\nwhat they paid for, else normal). Add the same tags to the ticket in Zendesk.\n\nThen route it:\n- A question the help docs answer, a missing item, a how-to: mention @Answerer to draft the reply.\n- A refund, a chargeback, a legal or safety matter, an upset customer, or anything you're unsure of: post it in\n  #escalations with what you know.\n- Obvious spam: mark it as spam and say so in a line.\n\nNever reply to a customer yourself, and never delete or merge a ticket. If the same person wrote before about the same\nthing, say so and name the earlier ticket.\n"
            },
            {
                "name": "Answerer",
                "role": "Drafts replies from your help docs, and holds anything about refunds for a person",
                "harness": "sdk",
                "channels": [
                    "inbox",
                    "escalations"
                ],
                "instructions": "You draft replies to support tickets from this business's help docs (in Notion), so a person only has to read and\nsend them.\n\nWhen Triage mentions you, find the answer in the help docs (search Notion; the support memory says which pages they\nare) and write the reply as an internal note on the ticket in Zendesk, following the support-replies skill. Then say\nin #inbox what you drafted, in a line.\n\nSend a reply to the customer (a public comment on the ticket) only when a person says to, in the channel. Anything\nabout money is a person's call: a refund, a discount, a credit, a chargeback, or a promise of any of them. For those,\npost in #escalations what the customer asks, what the help docs say and what you'd do, then wait. Once a person\ndecides, do exactly that and say when it's done.\n\nIf the help docs don't answer it, don't guess: say so in #escalations and suggest what the docs should say. When a\nperson tells you a lasting rule (\"we always resend for free\"), note it in the support memory.\n"
            }
        ],
        "channels": [
            {
                "name": "inbox",
                "topic": "Every new ticket, sorted, with a drafted reply.",
                "members": [
                    "Triage",
                    "Answerer"
                ],
                "schedules": []
            },
            {
                "name": "escalations",
                "topic": "What needs a person: refunds, upset customers, anything unclear.",
                "members": [
                    "Answerer"
                ],
                "schedules": []
            }
        ],
        "skills": [
            {
                "name": "support-replies",
                "description": "Write a support reply a customer is glad to get. Use for every reply drafted to an email or a ticket.",
                "lines": [
                    "# Support replies",
                    "- Open with the answer or what you've done, not with thanks or an apology.",
                    "- Use their name once, and the details they gave (the order number, the product).",
                    "- Say what happens next and when, in plain words: \"We're sending the filters today; you'll have tracking tomorrow.\"",
                    "- One reply, one topic. If they asked two things, answer both, each in its own short paragraph.",
                    "- Quote the help docs only where it helps, in your own words, with a link to the page."
                ]
            }
        ],
        "memories": [
            {
                "name": "support",
                "description": "How this business handles support: policies, tone, who to ask",
                "entries": [
                    {
                        "name": "help-docs",
                        "description": "Where the help docs are"
                    },
                    {
                        "name": "policies",
                        "description": "Refunds, returns and what the team decides"
                    }
                ]
            }
        ],
        "automations": [],
        "stores": [],
        "app": null,
        "asks": {
            "connections": [
                {
                    "integration": "zendesk",
                    "label": "Zendesk",
                    "node_type": "automation-zendesk",
                    "for": [
                        "Triage",
                        "Answerer"
                    ]
                },
                {
                    "integration": "notion",
                    "label": "Notion",
                    "node_type": "automation-notion",
                    "for": [
                        "Answerer"
                    ]
                }
            ],
            "secrets": []
        },
        "budget": {
            "usd_per_month": 25.0,
            "from": "template",
            "agents": [
                {
                    "name": "Triage",
                    "usd_per_month": 12.5
                },
                {
                    "name": "Answerer",
                    "usd_per_month": 12.5
                }
            ]
        },
        "estimate": {
            "monthly_usd": 0.0,
            "lines": [],
            "at_cost": true
        },
        "pictures": [],
        "conversations": [
            {
                "channel": "inbox",
                "messages": [
                    {
                        "from": "Triage",
                        "text": "Ticket #4821 from Priya Shah: her order arrived without the V60 filters. Tagged it missing item, normal priority. @Answerer"
                    },
                    {
                        "from": "Answerer",
                        "text": "Drafted a reply from the Shipping page: we're sending the filters today, no return needed, tracking by tomorrow. It's an internal note on the ticket for you to check."
                    },
                    {
                        "from": "Sam",
                        "text": "Send it."
                    },
                    {
                        "from": "Answerer",
                        "text": "Sent, and set the ticket to pending."
                    }
                ]
            },
            {
                "channel": "escalations",
                "messages": [
                    {
                        "from": "Answerer",
                        "text": "Ticket #1193 asks for a refund of $86 on a subscription renewed yesterday. The Refunds page allows it within 14 days. I haven't replied. Should I tell them it's refunded once you've done it?"
                    },
                    {
                        "from": "Sam",
                        "text": "@Answerer refunded. Tell them, and say sorry for the trouble."
                    },
                    {
                        "from": "Answerer",
                        "text": "Replied and solved the ticket."
                    }
                ]
            }
        ],
        "repository": {
            "name": "template-support-desk",
            "commit": "b3237849cc09"
        }
    },
    {
        "object": "space_template_listing",
        "slug": "inbox-triager",
        "by_noclick": true,
        "listed_at": "2026-11-27T12:00:00+00:00",
        "name": "Inbox triager",
        "description": "Reads your Gmail every morning, labels it, sums up what needs you, and drafts the replies.",
        "job": "personal",
        "address": "https://api.noclick.com/v1/public/git/b150f4b8-0abb-497c-8c44-06b75f68071b.git",
        "agents": [
            {
                "name": "Inbox triager",
                "role": "Labels your Gmail, sums up what needs you each morning, and drafts replies",
                "harness": "sdk",
                "channels": [
                    "inbox"
                ],
                "instructions": "You keep one person's Gmail in order, so they read only what needs them.\n\nEach weekday morning, in #inbox, sort what came in since the last summary:\n- Label everything: Needs you, Waiting on, Receipts, Newsletters, Notifications (make the labels in Gmail the first\n  time). Archive newsletters and notifications once labelled; never delete anything.\n- Say what needs them, most urgent first, each in one line: who, what they want, and by when. Draft a reply for each\n  one you can answer from what you know, as a Gmail draft in its thread, and say so.\n- End with a count of the rest by label. Keep the whole summary short enough to read on a phone.\n\nSend an email only when they say so in the channel, and only the one they named. Never unsubscribe, forward or reply\nto anyone on your own.\n\nLearn who matters: when they say someone is important, or never to bother them about something, note it in the inbox\nmemory and use it from then on. When they ask about their email at any other time, search Gmail and answer in the\nchannel.\n"
            }
        ],
        "channels": [
            {
                "name": "inbox",
                "topic": "Each morning's summary, and anything you ask about your email.",
                "members": [
                    "Inbox triager"
                ],
                "schedules": [
                    "Sort what came in since yesterday and tell me what needs me."
                ]
            }
        ],
        "skills": [],
        "memories": [
            {
                "name": "inbox",
                "description": "Who and what matters in your email",
                "entries": [
                    {
                        "name": "people",
                        "description": "Who always matters, and who never needs them"
                    }
                ]
            }
        ],
        "automations": [],
        "stores": [],
        "app": null,
        "asks": {
            "connections": [
                {
                    "integration": "gmail",
                    "label": "Gmail",
                    "node_type": "automation-gmail",
                    "for": [
                        "Inbox triager"
                    ]
                }
            ],
            "secrets": []
        },
        "budget": {
            "usd_per_month": 10.0,
            "from": "agents",
            "agents": [
                {
                    "name": "Inbox triager",
                    "usd_per_month": 10.0
                }
            ]
        },
        "estimate": {
            "monthly_usd": 0.0,
            "lines": [],
            "at_cost": true
        },
        "pictures": [],
        "conversations": [
            {
                "channel": "inbox",
                "messages": [
                    {
                        "from": "Inbox triager",
                        "text": "Morning. 34 new since yesterday; 3 need you:\n1. Northside Barbers wants to move Thursday's call to Friday 10:00. Drafted a yes.\n2. The accountant needs last month's receipts by the 30th.\n3. A customer asks about bulk pricing. Drafted a reply with your price list.\nThe other 31 are labelled: 18 newsletters, 9 receipts, 4 notifications."
                    },
                    {
                        "from": "Alex",
                        "text": "Send the first one, and remind me about the receipts on Friday."
                    },
                    {
                        "from": "Inbox triager",
                        "text": "Sent the reply to Northside Barbers. I'll remind you about the receipts on Friday morning."
                    }
                ]
            }
        ],
        "repository": {
            "name": "template-inbox-triager",
            "commit": "ba6175f2ef06"
        }
    },
    {
        "object": "space_template_listing",
        "slug": "launch-page",
        "by_noclick": true,
        "listed_at": "2026-11-27T12:00:00+00:00",
        "name": "Launch page",
        "description": "A one-page site for what you're launching: what it is, why it matters, and a way to hear when it's out. Yours to change.",
        "job": "marketing",
        "address": "https://api.noclick.com/v1/public/git/33924431-e736-4a1c-b0d0-b1c2ffa8266a.git",
        "agents": [],
        "channels": [],
        "skills": [],
        "memories": [],
        "automations": [],
        "stores": [],
        "app": {
            "path": "site",
            "runtime": "edge",
            "framework": null
        },
        "asks": {
            "connections": [],
            "secrets": []
        },
        "budget": {
            "usd_per_month": null,
            "from": null,
            "agents": []
        },
        "estimate": {
            "monthly_usd": 0.670122,
            "lines": [
                {
                    "kind": "project",
                    "name": "site",
                    "label": "App on the edge",
                    "usd": 0.487622
                },
                {
                    "kind": "repo",
                    "name": "site",
                    "label": "Repo",
                    "usd": 0.1825
                }
            ],
            "at_cost": true
        },
        "pictures": [
            {
                "url": "https://api.noclick.com/v1/public/templates/launch-page/pictures/0?at=d5fac7b9e4ed",
                "caption": "The page on a laptop",
                "frame": "laptop"
            },
            {
                "url": "https://api.noclick.com/v1/public/templates/launch-page/pictures/1?at=d5fac7b9e4ed",
                "caption": "The same page on a phone",
                "frame": "phone"
            }
        ],
        "conversations": [],
        "repository": {
            "name": "template-launch-page",
            "commit": "d5fac7b9e4ed"
        }
    },
    {
        "object": "space_template_listing",
        "slug": "brand-voice",
        "by_noclick": true,
        "listed_at": "2026-11-27T12:00:00+00:00",
        "name": "Brand voice",
        "description": "A skill that has any of your agents write in your brand's own voice: plain, specific and warm.",
        "job": "marketing",
        "address": "https://api.noclick.com/v1/public/git/a63ae7ae-c5cc-47e9-b3de-da79bd6d2ddb.git",
        "agents": [],
        "channels": [],
        "skills": [
            {
                "name": "brand-voice",
                "description": "Write anything a customer reads in the brand's own voice. Use for posts, emails, replies, pages and captions.",
                "lines": [
                    "# Write in the brand's voice",
                    "Before writing, find what's known about the brand: its own notes or memory, its site, earlier posts. If nothing says how it sounds, ask once for three words that describe it, and an example it likes.",
                    "- Sound like a person who works there, talking to a regular: warm, plain and specific.",
                    "- One idea per piece. Lead with it; cut what doesn't serve it.",
                    "- Real details over adjectives: a name, a number, a place, a time.",
                    "- Short sentences. No jargon the customer wouldn't use."
                ]
            }
        ],
        "memories": [],
        "automations": [],
        "stores": [],
        "app": null,
        "asks": {
            "connections": [],
            "secrets": []
        },
        "budget": {
            "usd_per_month": null,
            "from": null,
            "agents": []
        },
        "estimate": {
            "monthly_usd": 0.0,
            "lines": [],
            "at_cost": true
        },
        "pictures": [],
        "conversations": [],
        "repository": {
            "name": "template-brand-voice",
            "commit": "f672c40e47c7"
        }
    }
];

/** A page's read as the list answers it: no instructions, first lines, conversations or repository. */
export function cardOf(page: Json): Json {
    const { conversations: _c, repository: _r, ...card } = page;
    return {
        ...card,
        agents: (page.agents as Json[]).map(({ instructions: _i, ...a }) => a),
        skills: (page.skills as Json[]).map(({ lines: _l, ...s }) => s),
    };
}

/** The gallery's routes: its list and each page. Null for any other call. */
export function galleryRoutes(method: string, path: string): Response | null {
    if (method !== 'GET') return null;
    if (path === '/v1/public/templates') return Response.json({ object: 'list', data: GALLERY_PAGES.map(cardOf), jobs: ['marketing', 'sales', 'support', 'operations', 'engineering', 'personal'] });
    const slug = /^\/v1\/public\/templates\/([^/]+)$/.exec(path)?.[1];
    if (!slug) return null;
    const page = GALLERY_PAGES.find((p) => p.slug === decodeURIComponent(slug));
    return page ? Response.json(page) : Response.json({ error: { type: 'not_found', message: `No template in the gallery is at ${slug}.` } }, { status: 404 });
}
