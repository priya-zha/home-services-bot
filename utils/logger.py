import json
import os
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from utils.models import JobContext, Urgency

console = Console()
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "jobs.log")


def _write_log(entry: dict):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_bot_turn(bot_name: str, role: str, message: str):
    color_map = {
        "IntakeBot": "cyan",
        "BookingBot": "green",
        "EscalationBot": "red",
        "Orchestrator": "yellow",
        "Customer": "white",
    }
    color = color_map.get(bot_name, "white")
    label = f"[bold {color}][{bot_name}][/bold {color}]"
    console.print(f"{label} {message}")


def log_job(context: JobContext, final_response: str, bot_used: str):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "bot": bot_used,
        "urgency": context.urgency.value,
        "customer_name": context.customer_name,
        "customer_email": context.customer_email,
        "phone": context.phone,
        "address": context.address,
        "service_type": context.service_type.value if context.service_type else None,
        "problem": context.problem_description,
        "preferred_time": context.preferred_time,
        "final_response": final_response,
    }
    _write_log(entry)

    urgency_color = "red" if context.urgency == Urgency.EMERGENCY else "green"
    panel_text = Text()
    panel_text.append(f"Urgency: ", style="bold")
    panel_text.append(f"{context.urgency.value}\n", style=f"bold {urgency_color}")
    panel_text.append(context.to_summary())

    console.print(
        Panel(
            panel_text,
            title=f"[bold]Job Logged — {bot_used}[/bold]",
            border_style=urgency_color,
        )
    )
