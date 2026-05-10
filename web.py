import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import uuid
import traceback
from flask import Flask, request, jsonify, render_template
from utils.models import Urgency, JobContext
import orchestrator

app = Flask(__name__)
app.secret_key = os.urandom(24)

# In-memory session store: session_id -> {context, phase}
sessions: dict[str, dict] = {}

RETRY_MESSAGE = "Sorry, I didn't quite catch that — could you rephrase? I want to make sure I get the details right."


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "").strip()
    session_id = data.get("session_id")

    if not message:
        return jsonify({"error": "Empty message"}), 400

    try:
        # New conversation
        if not session_id or session_id not in sessions:
            session_id = str(uuid.uuid4())
            context, reply, urgency_determined = orchestrator.start_conversation(message)
            sessions[session_id] = {"context": context, "phase": "intake"}

            if urgency_determined:
                context, reply, done = orchestrator.route_to_specialist(context)
                sessions[session_id]["context"] = context
                sessions[session_id]["phase"] = "done" if done else "specialist"
                return jsonify({"reply": reply, "session_id": session_id, "done": done})

            return jsonify({"reply": reply, "session_id": session_id, "done": False})

        sess = sessions[session_id]
        context: JobContext = sess["context"]
        phase: str = sess["phase"]

        if phase == "done":
            return jsonify({"reply": "This conversation is complete. Refresh the page to start a new one.", "session_id": session_id, "done": True})

        if phase == "intake":
            context, reply, urgency_determined = orchestrator.continue_intake(message, context)
            sess["context"] = context
            if urgency_determined:
                context, reply, done = orchestrator.route_to_specialist(context)
                sess["context"] = context
                sess["phase"] = "done" if done else "specialist"
                return jsonify({"reply": reply, "session_id": session_id, "done": done})
            return jsonify({"reply": reply, "session_id": session_id, "done": False})

        if phase == "specialist":
            context, reply, done = orchestrator.next_specialist_turn(message, context)
            sess["context"] = context
            sess["phase"] = "done" if done else "specialist"
            return jsonify({"reply": reply, "session_id": session_id, "done": done})

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "reply": RETRY_MESSAGE,
            "session_id": session_id,
            "done": False
        })

    return jsonify({"reply": RETRY_MESSAGE, "session_id": session_id, "done": False})


@app.route("/history", methods=["POST"])
def history():
    data = request.get_json()
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"error": "Email required"}), 400
    conversations = orchestrator.get_history_by_email(email)
    return jsonify({"conversations": conversations})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
