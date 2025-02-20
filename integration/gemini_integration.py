import google.generativeai as genai
from flask import Blueprint, request, jsonify, session
from models.models import User, Insight, Action
from config import db
import os
import json

# Load environment variables
gemini_api_key = os.getenv("GEMINI_API_KEY")

# Initialize Gemini client
genai.configure(api_key=gemini_api_key)
model = genai.GenerativeModel('gemini-pro')

gemini_bp = Blueprint('gemini_bp', __name__)

@gemini_bp.route('/generate_insights', methods=['POST'])
def generate_insights():
    user_id = session.get("user_id")
    if not user_id:
        return {'error': 'User not authorized.'}, 401

    user = User.query.filter(User.id == user_id).first()
    user_personal_goal = user.personal_goals[0]
    goal_object = {
        "name": user_personal_goal.name,
        "saving_target": user_personal_goal.saving_target,
        "end_timeframe": user_personal_goal.end_timeframe
    }

    plaid_data = request.get_json()
    if not plaid_data or 'access_token' not in plaid_data:
        return jsonify({'error': 'Missing access_token'}), 400

    access_token = plaid_data['access_token']

    try:
        transactions_data = get_plaid_transactions(access_token).to_dict()

        insights_payload = {
            "transactions": transactions_data,
            "goal": goal_object
        }

        response = model.generate_content(insights_payload)
        insights_json = response.json()

        new_db_insight = Insight(
            savings_monthly=insights_json['savings_monthly'],
            savings_needed=insights_json['savings_needed'],
            strategy=insights_json['strategy'],
            personal_goal_id=user_personal_goal.id
        )

        db.session.add(new_db_insight)
        db.session.commit()

        for action in insights_json['actions']:
            new_db_action = Action(text=action, insight_id=new_db_insight.id)
            db.session.add(new_db_action)
            db.session.commit()

        return jsonify(insights_json)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
