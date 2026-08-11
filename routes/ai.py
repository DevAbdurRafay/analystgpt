import os
from flask import Blueprint, request, jsonify, session
import pandas as pd

from services.groq_service import groq_service
from services.supabase_service import db_service
from routes.data import get_dataset_path

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")


@ai_bp.route("/history", methods=["GET"])
def history():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session.get("user_id")
    if not user_id and session.get("email"):
        u = db_service.get_user_by_email(session.get("email"))
        if u:
            user_id = u.get("id")
            session["user_id"] = user_id

    if not user_id:
        return jsonify({"messages": []})

    messages = db_service.get_chat_messages(user_id)
    formatted = []
    for msg in messages:
        formatted.append({
            "sender": msg.get("sender", "user"),
            "text": msg.get("content", ""),
            "chart_type": msg.get("chart_type"),
            "chart_data": msg.get("chart_data"),
        })
    return jsonify({"messages": formatted})


@ai_bp.route("/query", methods=["POST"])
def query():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    dataset_path = get_dataset_path()
    if not dataset_path or not os.path.exists(dataset_path):
        return jsonify({"error": "No active dataset found. Please upload a CSV first."}), 400
        
    post_data = request.json or {}
    user_query = post_data.get("query", "").strip()
    
    if not user_query:
        return jsonify({"error": "Please enter a question for the assistant."}), 400
        
    try:
        df = pd.read_csv(dataset_path)
        
        # Call Groq analysis engine
        result = groq_service.query_data(df, user_query)
        
        # Save session & chat messages in Supabase
        user_id = session.get("user_id")
        if not user_id and session.get("email"):
            u = db_service.get_user_by_email(session.get("email"))
            if u:
                user_id = u.get("id")
                session["user_id"] = user_id

        if user_id:
            chat_session = db_service.get_or_create_chat_session(user_id=user_id)
            if chat_session and chat_session.get("id"):
                session_id = chat_session.get("id")
                # Save user message
                db_service.save_chat_message(session_id=session_id, sender="user", content=user_query)
                # Save AI message
                answer_content = result.get("answer", "")
                chart_type = result.get("chart_type")
                chart_data = result.get("chart_data")
                db_service.save_chat_message(
                    session_id=session_id,
                    sender="ai",
                    content=answer_content,
                    chart_type=chart_type,
                    chart_data=chart_data
                )

        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "error": f"AI analysis failed to execute: {str(e)}"
        }), 500

