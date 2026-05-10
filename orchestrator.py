import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

from utils.models import JobContext, Urgency
from utils import logger
import bots.intake_bot as intake_bot
import bots.booking_bot as booking_bot
import bots.escalation_bot as escalation_bot

load_dotenv()

MAX_INTAKE_TURNS = 3


def _send_email(subject: str, body: str, recipient: str):
    sender = os.getenv("GMAIL_ADDRESS")
    app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not all([sender, app_password, recipient]):
        logger.console.print("[yellow][Email] Skipped — credentials not set[/yellow]")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, app_password)
            server.sendmail(sender, recipient, msg.as_string())

        logger.console.print(f"[green][Email] Sent to {recipient}[/green]")
    except Exception as e:
        logger.console.print(f"[red][Email] Failed ({recipient}): {e}[/red]")


def _notify_owner_emergency(context: JobContext):
    body = (
        f"EMERGENCY — CALL BACK IMMEDIATELY\n\n"
        f"Customer: {context.customer_name or 'Unknown'}\n"
        f"Problem: {context.problem_description or 'Not specified'}\n"
        f"Phone: {context.phone or 'Not provided'}\n"
        f"Address: {context.address or 'Not provided'}\n"
        f"Email: {context.customer_email or 'Not provided'}\n\n"
        f"{'='*40}\n"
        f"CONVERSATION TRANSCRIPT\n"
        f"{'='*40}\n"
        f"{context.conversation_transcript()}"
    )
    _send_email("🚨 HomeBot EMERGENCY", body, os.getenv("OWNER_EMAIL", ""))


def _notify_owner_booking(context: JobContext):
    body = (
        f"New Job Booked\n\n"
        f"Customer: {context.customer_name or 'Unknown'}\n"
        f"Email: {context.customer_email or 'Not provided'}\n"
        f"Phone: {context.phone or 'Not provided'}\n"
        f"Service: {context.service_type.value if context.service_type else 'Not specified'}\n"
        f"Problem: {context.problem_description or 'Not specified'}\n"
        f"Address: {context.address or 'Not provided'}\n"
        f"Preferred time: {context.preferred_time or 'Not provided'}\n"
        f"Timezone: {context.timezone or 'Not provided'}\n\n"
        f"{'='*40}\n"
        f"CONVERSATION TRANSCRIPT\n"
        f"{'='*40}\n"
        f"{context.conversation_transcript()}"
    )
    _send_email("HomeBot — New Booking", body, os.getenv("OWNER_EMAIL", ""))


def _confirm_customer_booking(context: JobContext):
    if not context.customer_email:
        return
    body = (
        f"Hi {context.customer_name or 'there'},\n\n"
        f"We've received your service request and someone from our team will be in touch shortly to confirm your appointment.\n\n"
        f"Here's what we have on file:\n"
        f"Service: {context.service_type.value if context.service_type else 'Home service'}\n"
        f"Problem: {context.problem_description or 'Not specified'}\n"
        f"Address: {context.address or 'Not provided'}\n"
        f"Preferred time: {context.preferred_time or 'Not provided'}\n"
        f"Timezone: {context.timezone or 'Not provided'}\n"
        f"Phone: {context.phone or 'Not provided'}\n\n"
        f"If anything changes or you need immediate assistance, reply to this email.\n\n"
        f"— HomeBot"
    )
    _send_email("Your service request has been received", body, context.customer_email)


def _confirm_customer_emergency(context: JobContext):
    if not context.customer_email:
        return
    body = (
        f"Hi {context.customer_name or 'there'},\n\n"
        f"We've received your emergency request and flagged it as urgent. Someone from our team will call you back as soon as possible.\n\n"
        f"Details on file:\n"
        f"Problem: {context.problem_description or 'Not specified'}\n"
        f"Address: {context.address or 'Not provided'}\n"
        f"Phone: {context.phone or 'Not provided'}\n\n"
        f"If this is a life-threatening emergency, please call 911.\n\n"
        f"— HomeBot"
    )
    _send_email("🚨 Emergency request received — we're on it", body, context.customer_email)


def start_conversation(initial_message: str) -> tuple[JobContext, str, bool]:
    """
    Processes the first customer message through IntakeBot.
    Returns (context, reply, urgency_determined).
    If urgency_determined is False, the caller should collect more input and call continue_intake().
    """
    context = JobContext()
    logger.console.rule("[bold blue]New Conversation[/bold blue]")
    logger.log_bot_turn("Customer", "user", initial_message)

    context, reply, needs_more = intake_bot.run(initial_message, context)
    logger.log_bot_turn("IntakeBot", "assistant", reply)

    urgency_determined = context.urgency in (Urgency.EMERGENCY, Urgency.ROUTINE)
    return context, reply, urgency_determined


def continue_intake(user_message: str, context: JobContext) -> tuple[JobContext, str, bool]:
    """Called when intake needs more info. Returns (context, reply, urgency_determined)."""
    logger.log_bot_turn("Customer", "user", user_message)
    # intake_bot.run() handles adding both user + assistant messages to history internally
    context, reply, _ = intake_bot.run(user_message, context)
    logger.log_bot_turn("IntakeBot", "assistant", reply)
    urgency_determined = context.urgency in (Urgency.EMERGENCY, Urgency.ROUTINE)
    return context, reply, urgency_determined


def next_specialist_turn(user_message: str, context: JobContext) -> tuple[JobContext, str, bool]:
    """
    Adds customer message to history and runs the appropriate specialist bot.
    Returns (context, reply, conversation_done).
    """
    logger.log_bot_turn("Customer", "user", user_message)
    context.conversation_history.append({"role": "user", "content": user_message})

    if context.urgency == Urgency.EMERGENCY:
        context, reply, done = escalation_bot.run(context)
        logger.log_bot_turn("EscalationBot", "assistant", reply)
    else:
        context, reply, done = booking_bot.run(context)
        logger.log_bot_turn("BookingBot", "assistant", reply)

    if done:
        _finalize(context)

    return context, reply, done


def route_to_specialist(context: JobContext) -> tuple[JobContext, str, bool]:
    """
    Called once after intake is complete to get the first specialist response.
    Returns (context, reply, conversation_done).
    """
    if context.urgency == Urgency.EMERGENCY:
        logger.log_bot_turn("Orchestrator", "system", "Routing to EscalationBot (EMERGENCY)")
        context, reply, done = escalation_bot.run(context)
        logger.log_bot_turn("EscalationBot", "assistant", reply)
    else:
        logger.log_bot_turn("Orchestrator", "system", "Routing to BookingBot (ROUTINE)")
        context, reply, done = booking_bot.run(context)
        logger.log_bot_turn("BookingBot", "assistant", reply)

    if done:
        _finalize(context)

    return context, reply, done


def _finalize(context: JobContext):
    """Logs the job and sends all emails when a conversation completes."""
    bot_name = "EscalationBot" if context.urgency == Urgency.EMERGENCY else "BookingBot"
    logger.log_job(context, "", bot_name)

    if context.urgency == Urgency.EMERGENCY:
        _notify_owner_emergency(context)
        _confirm_customer_emergency(context)
    else:
        _notify_owner_booking(context)
        _confirm_customer_booking(context)
