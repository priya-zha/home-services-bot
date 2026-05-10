import json
import re
import anthropic
from utils.models import JobContext


def _extract_email(text: str):
    match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None


def _extract_phone(text: str):
    match = re.search(r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}", text)
    return match.group(0) if match else None

SYSTEM_PROMPT = """You are the Escalation Bot for a home services company. You handle EMERGENCIES only.

Your job:
1. Acknowledge the emergency immediately — no small talk, straight to help
2. Give relevant safety instructions for their specific situation
3. Collect: full address, email address, and phone number (optional)
4. Reassure the customer that this is flagged as urgent and someone will call back ASAP

Required before closing:
- Full address
- Email address (for follow-up confirmation)

Optional:
- Phone number (ask once, don't block if they skip it)

Safety instructions by situation:
- Burst pipe / flooding: Shut off main water valve (near water meter or where main line enters house)
- Gas smell: Leave immediately, no switches, call 911 and gas company from outside
- No heat (winter): Blankets, close unused rooms, never use oven/grill to heat
- Sewage backup: Avoid all drains and toilets, keep kids and pets away
- No AC (extreme heat): Coolest room, stay hydrated, fans if available — call 911 if heat exhaustion
- Electrical / sparks: Turn off circuit breaker if safe, do not touch wires, call 911 if fire risk

Rules:
- Safety instructions come BEFORE collecting info — customer safety first
- Stay calm and authoritative — panicked responses make customers panic more
- Always end with: "I've flagged this as an emergency. You'll receive a confirmation email and hear from us very soon."
- Collect address and email even if customer seems in crisis — needed for dispatch and follow-up

IMPORTANT: Always respond with JSON only. No text before or after.

JSON format:
{
  "reply_to_customer": "your message to the customer",
  "address": "full address or null",
  "customer_email": "email address or null",
  "phone": "phone number or null",
  "escalation_complete": true or false
}"""


def run(context: JobContext) -> tuple[JobContext, str, bool]:
    client = anthropic.Anthropic()

    context_summary = context.to_summary()
    system_with_context = (
        f"{SYSTEM_PROMPT}\n\n"
        f"--- WHAT WE ALREADY KNOW ---\n{context_summary}\n"
        f"----------------------------"
    )

    messages = context.conversation_history.copy()
    # Sonnet requires conversation ends with a user message
    while messages and messages[-1]["role"] == "assistant":
        messages.pop()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
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
            data = {"reply_to_customer": raw, "escalation_complete": False}

    if data.get("address"):
        context.address = data["address"]
    if data.get("customer_email"):
        context.customer_email = data["customer_email"]
    if data.get("phone"):
        context.phone = data["phone"]

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

    escalation_complete = data.get("escalation_complete", False)
    return context, reply, escalation_complete
