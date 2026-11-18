# ---
# description: A real phone number that answers like a front desk, books into the business's Google Calendar, texts callers their confirmation and puts the hard calls through to the owner.
# card_title: A receptionist on a real number
# card_line: Answers, books and texts confirmations.
# mark: phone
# cmd: ["python", "03_voice_and_email/phone_receptionist.py"]
# env: ["NOCLICK_API_KEY", "OWNER_EMAIL", "OWNER_PHONE"]
# deps: []
# featured: true
# ---

# # An AI receptionist on a real phone number
#
# A small business misses calls all day. The owner is with a client, the phone rings out, and
# the caller books somewhere else. This example gives one a receptionist: a local number that
# answers every call in a natural voice, knows the hours, services and prices, books the
# appointment straight into the business's Google Calendar, texts the caller a confirmation, and
# puts the calls it shouldn't handle through to the owner.
#
# It's written the way your product would run it for many businesses. Each business is one of
# your [users](/docs/guide/users), so its calendar, its number, its receptionist and what they
# cost are its own, and its owner is the person NoClick reaches when something needs a person.
#
# You play the owner. `OWNER_EMAIL` gets the link to connect a Google Calendar, and
# `OWNER_PHONE` is the phone that rings when the receptionist puts a caller through.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# export OWNER_EMAIL=you@example.com
# export OWNER_PHONE=+15035550123
# python 03_voice_and_email/phone_receptionist.py
# ```
#
# The first run sets everything up and prints the number: call it. Every later run sets the
# receptionist's fields from this file again, tries it on a test call, and shows today's calls,
# bookings and spend. Nothing is created twice.

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import noclick

# ## The business
#
# Everything the receptionist knows about the business is here. In your product this is what
# the owner typed in when they signed up. The instructions are built from it, so when the owner
# changes a price, running this again is how the change reaches the phone line.

BUSINESS_ID = "juniper-hair"  # your id for this business
NAME = "Juniper Hair Studio"
ADDRESS = "2417 SE Division St, Portland, OR 97202"
TIMEZONE = "America/Los_Angeles"
AREA_CODE = "503"
SPEND_CAP_USD = 150  # the most everything for this business may cost in a month
OWNER = "Maya"
OWNER_EMAIL = os.environ["OWNER_EMAIL"]
OWNER_PHONE = os.environ["OWNER_PHONE"]  # E.164: where put-through calls ring

HOURS = "Tuesday to Friday 10am to 7pm, Saturday 9am to 5pm, closed Sunday and Monday"
SERVICES = [  # name, minutes, dollars
    ("Women's cut and style", 60, 85),
    ("Men's cut", 30, 45),
    ("Kids' cut, under 12", 30, 30),
    ("Blowout", 45, 50),
    ("Single-process color", 90, 120),
    ("Full highlights", 150, 210),
]


def instructions() -> str:
    menu = "\n".join(f"- {name}: {minutes} minutes, ${price}" for name, minutes, price in SERVICES)
    return f"""You answer the phone at {NAME}, a hair salon at {ADDRESS}.
Talk like a friendly front desk: short sentences, one question at a time, never a list read aloud.

Opening hours: {HOURS}.
Services, how long each takes and what it costs:
{menu}
Cancellations need 24 hours' notice, or there's a $25 fee. We take cards and cash.

To book:
1. Ask which service, then what day and time suits them, and their first name.
2. Check the calendar "primary" with query_calendar_availability, in {TIMEZONE} time. Offer a free
   time inside opening hours that fits the service. Never offer a time you haven't checked.
3. Read the day, time and service back, and wait for a yes.
4. Book it with create_calendar_event: the title is the service and their first name, the
   description has their phone number, and it lasts as long as the service.
5. Text them a confirmation with send_text: the service, the day and time, the address and the
   cancellation rule. If you have no send_text, read that confirmation out instead.

You book new appointments only. To move or cancel one, or for anything else you can't do (a refund,
a complaint, a price that isn't on the list), or when the caller is upset or asks for the owner:
tell them you're putting them through to {OWNER}, the owner, and use transfer_call. If she doesn't
pick up, or it's outside opening hours, say she'll call back today and notify her with their name,
number and what they need.

Never make up a price, a service or a free time. If you don't know, say so."""


# ## The business is one of your users
#
# A [user](/docs/guide/users) is someone your product acts for, and a company counts. Created
# here with the owner's email, it scopes everything below: the calendar connection is the
# business's, the receptionist and the number belong to it, and `business.human` is the owner.
#
# `spend_cap_usd_per_month` is the most the business's calls, texts and receptionist turns may cost
# in a month. Set it well above a normal month: it's there so a spam caller who keeps the line busy
# all night can only cost so much.


def business_user() -> noclick.User:
    return noclick.User.from_id(
        BUSINESS_ID, create_if_missing=True, name=NAME, email=OWNER_EMAIL, spend_cap_usd_per_month=SPEND_CAP_USD,
    )


# ## Connect the business's calendar
#
# The receptionist books into the owner's own Google Calendar, so there's no second calendar to
# keep in step: bookings show up next to everything else in her day, and a slot she blocks on her
# phone is one the receptionist won't offer.
#
# `business.human.connect` emails the owner a link to connect it, then waits until she has. The
# calendar is a [connection](/docs/guide/connections) named `calendar`, so this line finds it on
# every later run and only asks once.


def connect_calendar(business: noclick.User) -> noclick.Connection:
    calendar = noclick.Connection.from_name("calendar", integration="google_calendar", create_if_missing=True)
    if not calendar.connected:
        link = business.human.connect(calendar, reason="so your receptionist can book appointments for you")
        print(f"Emailed {OWNER_EMAIL} a link to connect Google Calendar: {link.url}")
        link.wait()
    print("Booking into:", calendar.refresh().account)
    return calendar


# ## Hire the receptionist
#
# The receptionist is an [agent](/docs/guide/agents). Its tools are two operations of the
# calendar, not the whole calendar: it can see when the owner is free and add a booking, and it
# can't move, change or delete anything already there. Moves and cancellations go to the owner:
# they touch appointments other people already hold.
#
# The owner is a tool too. `business.human.only("notify")` lets the receptionist send her a note,
# and nobody else: when a caller needs her and she can't take the call, the callback lands in her
# inbox instead of being buried in a transcript.
#
# `timezone` starts every turn with the date and time in Portland, so "this Saturday" is a date the
# receptionist can check the calendar for.
#
# `from_name` with `create_if_missing=True` sets the agent's fields from this code every time it
# runs: new prices in `SERVICES` reach the next call after you run the script.


def hire_receptionist(business: noclick.User, calendar: noclick.Connection) -> noclick.Agent:
    return noclick.Agent.from_name(
        "receptionist",
        create_if_missing=True,
        instructions=instructions(),
        tools=[
            calendar.only("query_calendar_availability", "create_calendar_event"),
            business.human.only("notify"),
        ],
        timezone=TIMEZONE,
    )


# ## Give it a phone number
#
# The business owns one number, named `front-desk`. The first run buys a local one in its area
# code; later runs find the same one. `max_monthly_usd` and `max_upfront_usd` are your ceilings: a
# number that costs more a month, or once when it's bought, isn't bought.
#
# [`answer_with`](/docs/reference/python/PhoneNumber#PhoneNumber.answer_with) sends every call to
# the receptionist, with its calendar tools working on the call as they do in a message. On the
# line it gets two tools only a phone has. `transfer_to` gives it `transfer_call`, which puts the
# caller through to the owner's phone; a transfer she doesn't pick up comes back to the
# receptionist. `texts=True` gives it `send_text`, which texts the caller and nobody else, the way
# an inbox's reply goes only to the sender, so no caller can have the receptionist text a stranger.
#
# Texting from a US number needs your business registered with the carriers first, once, as a
# [`TextingRegistration`](/docs/reference/python/PhoneNumber#TextingRegistration). Until that's
# approved, `texts=True` raises `noclick.ActionRequired` naming the registration, and the line
# answers without texts in the meantime: the receptionist reads the booking back instead.


def phone_line(receptionist: noclick.Agent) -> noclick.PhoneNumber:
    number = noclick.PhoneNumber.from_name(
        "front-desk", create_if_missing=True, area_code=AREA_CODE, max_monthly_usd=5, max_upfront_usd=5,
    )
    try:
        return number.answer_with(receptionist, transfer_to=OWNER_PHONE, texts=True)
    except noclick.ActionRequired as err:
        print(f"Texting isn't approved yet: {err.message}\n  {err.next_step}")
        return number.answer_with(receptionist, transfer_to=OWNER_PHONE)


# ## Try it before a caller does
#
# A [test run](/docs/guide/testing) is a real turn of the receptionist, with its instructions and
# tools, where a simulated world answers every tool call. Nothing is booked and nobody is texted,
# so it's safe to run after every change. The scenario says what that world is like: here, a
# Saturday that's busy first thing.


def rehearse(receptionist: noclick.Agent) -> None:
    run = receptionist.rehearse(
        "Hi, it's Sam. Do you have anything Saturday morning for a men's cut?",
        scenario=(
            "It's Wednesday afternoon. Saturday is booked from 9:00 to 10:30 and free after that. "
            "Sam is calling from +15035550147 and takes the first time offered."
        ),
    ).wait()
    print("\nTest call:", run.reply)
    for call in run.tool_calls:
        print("  ", call["tool"], call["arguments"])


# ## Who called today
#
# Everything the owner wants to know at the end of the day already exists: the number keeps each
# call it answered, with its transcript, length and cost, and every booking is a tool call the
# receptionist made. Neither needs copying anywhere.


def today(number: noclick.PhoneNumber, receptionist: noclick.Agent) -> None:
    midnight = datetime.now(ZoneInfo(TIMEZONE)).replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\nCalls to {number.number} today:")
    for call in number.calls(direction="inbound", since=midnight):
        print(f"\n{call.created_at}  from {call.from_number}  {call.status}, {call.seconds}s, ${call.cost_usd}")
        print(call.text)

    print("\nBooked today:")
    for booking in noclick.ToolCall.list(agent=receptionist, tool="google_calendar.create_calendar_event", since=midnight):
        print(" ", booking.status, booking.arguments.get("start_time"), booking.arguments.get("summary"))

    month = noclick.usage()
    print(f"\n{NAME} this month: ${month.total_usd:.2f} of its ${SPEND_CAP_USD} cap, plus ${number.monthly_usd} for the number")


# ## Stop paying for it
#
# The number is billed monthly until you release it. Run the script with `release` to give the
# number back and remove the receptionist and the calendar connection:
#
# ```bash
# python 03_voice_and_email/phone_receptionist.py release
# ```


def release() -> None:
    with noclick.as_user(BUSINESS_ID):
        noclick.PhoneNumber.from_name("front-desk").release()
        noclick.Agent.from_name("receptionist").delete()
        noclick.Connection.from_name("calendar").delete()
    print("Released the number and removed the receptionist.")


def main() -> None:
    if sys.argv[1:] == ["release"]:
        release()
        return
    business = business_user()
    with noclick.as_user(business):
        calendar = connect_calendar(business)
        receptionist = hire_receptionist(business, calendar)
        number = phone_line(receptionist)
        print(f"\n{NAME}'s receptionist answers {number.number}. Call it.")
        rehearse(receptionist)
        today(number, receptionist)


if __name__ == "__main__":
    main()
