from flask import Blueprint, jsonify, request
from flask_login import current_user

from helpers import role_required
from extensions import db
from models import LoanApplication
from services import chatbot_response_for_student, evaluate_application_ai


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.post("/ai/evaluate/<int:application_id>")
@role_required("admin")
def evaluate_application_ai_api(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    payload = evaluate_application_ai(application)
    db.session.commit()
    return jsonify(payload)


@api_bp.post("/chatbot")
@role_required("student")
def chatbot_api():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or request.form.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Type a short question about application status, corrections, or eligibility."}), 400

    return jsonify({"reply": chatbot_response_for_student(current_user, message)})
