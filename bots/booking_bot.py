import json
import re
from datetime import date
import anthropic
from utils.models import JobContext


def _extract_email(text: str):
    match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None


def _extract_phone(text: str):
    match = re.search(r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}", text)
    return match.group(0) if match else None

SYSTEM_PROMPT = """You are the Booking Bot for a home services company handling routine (non-emergency) requests.

YOU MUST ALWAYS RESPOND WITH VALID JSON ONLY. No text before or after the JSON object.

Collect these fields before setting booking_complete to true:
- customer_name (ask once — if they skip it, proceed without it)
- address (full street + city)
- customer_email
- phone (REQUIRED — technician needs to call ahead)
- preferred_time (day/window like "Monday morning")
- timezone (Eastern, Central, Mountain, Pacific, etc.)

If the customer asks about COST or PRICE:
- Say pricing depends on the job and the tech gives a quote on-site before any work starts.
- Offer a choice: get booked now, OR leave their number for a callback to discuss costs first.
- If they choose callback: phone and email are required. Set path to "callback". Close once you have both.
- If they choose booking: collect all fields above. Set path to "booking".

Rules:
- Never quote specific prices.
- Never promise a specific appointment time — say "we'll confirm shortly".
- Ask for 1-2 missing fields at a time, not everything at once.
- Never set booking_complete to true if phone is missing.

JSON format (respond with this structure every single time):
{
  "reply_to_customer": "your conversational message here",
  "path": "booking or callback or unknown",
  "customer_name": "value or null",
  "address": "value or null",
  "customer_email": "value or null",
  "phone": "value or null",
  "preferred_time": "value or null",
  "timezone": "value or null",
  "booking_complete": false
}"""


def run(context: JobContext) -> tuple[JobContext, str, bool]:
    client = anthropic.Anthropic()

    today = date.today()
    today_str = today.strftime("%A, %B %d, %Y")  # e.g. "Saturday, May 09, 2026"

    context_summary = context.to_summary()
    system_with_context = (
        f"{SYSTEM_PROMPT}\n\n"
        f"TODAY'S DATE: {today_str}\n"
        f"When the customer says 'today', 'tomorrow', 'Monday', 'next week', etc., "
        f"resolve it to the actual calendar date based on today's date above. "
        f"Store preferred_time as a full date string, e.g. 'Monday, May 11, 2026 - Morning'.\n\n"
        f"--- WHAT WE ALREADY KNOW ---\n{context_summary}\n"
        f"----------------------------\n"
        f"Only ask for information that is still missing."
    )

    messages = context.conversation_history.copy()
    # Sonnet requires conversation ends with a user message
    while messages and messages[-1]["role"] == "assistant":
        messages.pop()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system_with_context,
        messages=messages,
    )

    raw = response.content[0].text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError):
            # Bot returned unparseable output — keep conversation going
            data = {"reply_to_customer": raw, "booking_complete": False}

    if data.get("customer_name"):
        context.customer_name = data["customer_name"]
    if data.get("address"):
        context.address = data["address"]
    if data.get("customer_email"):
        context.customer_email = data["customer_email"]
    if data.get("phone"):
        context.phone = data["phone"]
    if data.get("preferred_time"):
        context.preferred_time = data["preferred_time"]
    if data.get("timezone"):
        context.timezone = data["timezone"]

    reply = data.get("reply_to_customer", "")

    # Fallback: extract from reply text if JSON fields were missing
    full_text = raw + " " + reply
    if not context.customer_email:
        context.customer_email = _extract_email(full_text)
    if not context.phone:
        context.phone = _extract_phone(full_text)

    # Avoid consecutive assistant messages (Anthropic API requires alternating roles)
    if context.conversation_history and context.conversation_history[-1]["role"] == "assistant":
        context.conversation_history[-1]["content"] = reply
    else:
        context.conversation_history.append({"role": "assistant", "content": reply})

    booking_complete = data.get("booking_complete", False)
    path = data.get("path", "unknown")

    # Safety gate — never allow completion without required fields
    if booking_complete:
        if path == "callback" and not context.phone:
            booking_complete = False
        elif path == "booking" and not all([context.phone, context.address, context.customer_email, context.preferred_time]):
            booking_complete = False

    return context, reply, booking_complete
