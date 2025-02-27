from flask import Flask, Blueprint, request, jsonify, session
from models.models import * 
from config import api, db
from datetime import datetime, timedelta

from plaid.api import plaid_api
import plaid
from plaid.api import plaid_api
import google.generativeai as genai
from dotenv import load_dotenv
import os
import json
import requests

# Load the .env file. If it's in the same directory as your script, you can call load_dotenv() without any arguments.
load_dotenv()

gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
model = genai.GenerativeModel('gemini-pro')

client_id = os.getenv('PLAID_CLIENT_ID')
secret_id = os.getenv('PLAID_SECRET')

configuration = plaid.Configuration(
    host=plaid.Environment.Sandbox,
    api_key={
        'clientId': client_id,
        'secret': secret_id,
    }
)

api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)

system_prompt = "You are a helpful, financial analyst AI assistant that specializes in personal finance designed to output in valid JSON. You can analyze a user's financial data efficiently and accurately, including bank information, and transactions, to provide budget recommendations based on given information. When providing recommended action items, make sure to use transactions to give a more personalized and feasible response. You can also make future projections based on this data. If a user has a specific financial goal, you can suggest strategies to help them save money and reach their goal. You can accurately calculate sums, amounts, and budget predictions based off of data given to you."

savings_example_json = "{'savings_monthly': amount of suggested monthly savings per month from today's date to the end date for the goal and based off income, savings goal, transactions, and income, 'savings_needed': amount of savings needed to reach goal based off goal and current savings_balance, 'strategy': suggestions in a string for a strategy on how to reach goal from the information given, 'actions': recommended personalized, feasible actions that can be taken from the given information and from suggestions in a few strings within an array. If string mentions a specific category to save in, include total amount spent in that category based on previous month spending}"

insights_system_prompt = "You are a financial analyst AI assistant specialized in personal finance designed to output in valid JSON. You can efficiently and accurately analyze a user's financial data, including bank transactions, categories of each transaction, and the amount spent in each transaction. Based on this data, you can provide predictions of a user's future total spending in each category for the following month. Your recommendations should be tailored and accurate, ensuring the user can make informed financial decisions."

insights_assistant = "{'projections': {'each category is a key, create as many as needed. if a category does not have a projected amount for the following month or there is not enough data to make a predictions, do not include it': 'the total amount spent in that specific category within the past month this float format 100.10'}}"


def get_plaid_transactions(access_token):
        
    # Setup the dates for fetching transactions
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    try:
        transactions_request = {
            'access_token': access_token,
            'start_date': start_date,
            'end_date': end_date,
        }
        
        response = plaid_client.transactions_get(transactions_request)
        return response
    except plaid.ApiException as e:
        return jsonify({'error': str(e)})
    

open_ai = Blueprint('open_ai', __name__)

@open_ai.route('/response', methods=['POST'])
def ai_response():
    # checks if user has a session
    user_id = session.get("user_id")
    print(f"Retrieved user_id from session: {user_id}")
    
    if not user_id:
        return {'error': 'User not authorized.'}, 401

    user = User.query.filter(User.id == user_id).first()
    # There are multiple goals to a user, but we're picking the first one for demo purposes
    # will need to add logic to check which goal a user has chosen..
    # id = request.get_json()["id"]
    user_personal_goal = user.personal_goals[0]
    goal_object = {
        "name": user_personal_goal.name,
        "saving_target": user_personal_goal.saving_target,
        "end_timeframe": user_personal_goal.end_timeframe
    }
    
    # from the 
    plaid_data = request.get_json()
    if not plaid_data or 'access_token' not in plaid_data:
        return jsonify({'error': 'Missing access_token'}), 400

    access_token = plaid_data['access_token']
    
    try:
        # Get the transactions data from the request
        transactions_response = get_plaid_transactions(access_token)
        transactions_data = transactions_response.to_dict()

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