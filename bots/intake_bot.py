import json
import anthropic
from utils.models import JobContext, Urgency, ServiceType

SYSTEM_PROMPT = """You are the Intake Bot for a home services company (plumbing, HVAC, cleaning, electrical).
You are the first responder — every inbound customer message comes to you first.

YOU MUST ALWAYS RESPOND WITH VALID JSON ONLY. No text before or after the JSON object.

Your job:
1. Greet the customer warmly on the first message
2. Understand what service they need and what the problem is
3. Classify urgency as EMERGENCY or ROUTINE

Emergency signals (classify as EMERGENCY immediately):
- Burst pipe, flooding, active water leak, sewage backup
- No heat in winter, no AC in extreme heat
- Gas smell or suspected gas leak
- Electrical sparks, burning smell, fire risk
- Any situation with active safety risk or ongoing damage

Everything else is ROUTINE.

Rules:
- If an emergency signal is present, set urgency to EMERGENCY immediately.
- If the problem is clearly a routine service request, set urgency to ROUTINE.
- If genuinely unclear, set urgency to UNKNOWN and ask one clarifying question.
- Keep reply_to_customer short and human — 2 sentences max.
- Once you know the service type and have a basic problem description, set urgency to ROUTINE and stop asking questions.

JSON format (respond with this exact structure every time):
{
  "reply_to_customer": "your message here",
  "customer_name": "name or null",
  "phone": "phone number or null",
  "service_type": "plumbing or hvac or cleaning or electrical or other",
  "problem_description": "brief description or null",
  "urgency": "EMERGENCY or ROUTINE or UNKNOWN",
  "needs_more_info": false
}"""


def run(customer_message: str, context: JobContext) -> JobContext:
    client = anthropic.Anthropic()

    messages = context.conversation_history.copy()
    # Drop trailing assistant messages before appending new user turn
    while messages and messages[-1]["role"] == "assistant":
        messages.pop()
    messages.append({"role": "user", "content": customer_message})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
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
            data = {
                "reply_to_customer": raw,
                "urgency": "UNKNOWN",
                "needs_more_info": True,
            }

    if data.get("customer_name"):
        context.customer_name = data["customer_name"]
    if data.get("phone"):
        context.phone = data["phone"]
    if data.get("problem_description"):
        context.problem_description = data["problem_description"]
    if data.get("service_type"):
        try:
            context.service_type = ServiceType(data["service_type"])
        except ValueError:
            context.service_type = ServiceType.OTHER
    if data.get("urgency") in ("EMERGENCY", "ROUTINE"):
        context.urgency = Urgency(data["urgency"])

    context.conversation_history.append({"role": "user", "content": customer_message})
    context.conversation_history.append(
        {"role": "assistant", "content": data.get("reply_to_customer", "")}
    )

    return context, data.get("reply_to_customer", ""), data.get("needs_more_info", False)
