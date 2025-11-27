# listener.py
import re # <--- ADD THIS AT THE TOP
from main import start_deal_process
import os
import json
from flask import Flask, request, Response, render_template, redirect, url_for,jsonify
from tools import get_open_opportunities, update_contact_email
import xmltodict
import threading
import uuid

# Import the agent functions from your main.py file
from main import start_deal_process, finalize_deal 
# Import the new tool from tools.py
from tools import get_open_opportunities

from langchain.callbacks.base import BaseCallbackHandler

app = Flask(__name__)
tasks = {}
tasks_lock = threading.Lock()

# --- NEW CLASS: Agent Log Listener ---
# 1. Update the AgentLogHandler class
class AgentLogHandler(BaseCallbackHandler):
    def __init__(self, task_id, opp_id):
        self.task_id = task_id
        # --- FIX 1: SAVE THE OPPORTUNITY ID ---
        self.opp_id = opp_id 
        # --------------------------------------
        self.prefix = f"[{opp_id}] "
        self.last_message = ""
        self.account_name = "Client" 
        self.sow_sent = False # Track if we actually sent it
    
    def update_status(self, status_text):
        with tasks_lock:
            if self.task_id in tasks:
                tasks[self.task_id]['current_step'] = status_text

    def save_envelope_id(self, envelope_id):
        with tasks_lock:
            if self.task_id in tasks:
                # Map the Opportunity ID to the Envelope ID
                tasks[self.task_id]['results'][self.opp_id] = envelope_id

    def mark_deal_complete(self):
        """Adds the account name to the finished list for the UI"""
        with tasks_lock:
            if self.task_id in tasks:
                # Only add if not already there to avoid duplicates
                if self.account_name not in tasks[self.task_id]['finished_deals']:
                    tasks[self.task_id]['finished_deals'].append(self.account_name)

    def log(self, message):
        if message == self.last_message: return
        self.last_message = message
        with tasks_lock:
            if self.task_id in tasks:
                tasks[self.task_id]['logs'].append(self.prefix + message)

    # --- EVENT HANDLERS ---

    def on_chain_start(self, serialized, inputs, **kwargs):
        # --- FIX 2: CHECK IF SERIALIZED EXISTS ---
        # Sometimes 'serialized' is None, causing the 'NoneType' error.
        if serialized and serialized.get("name") == "AgentExecutor":
            self.log("🤖 Agent activated.")
            self.update_status("🧠 Agent Initializing...")

    def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized['name']
        
        if "Create Composite SOW" in tool_name:
            try:
                args = json.loads(input_str)
                found_name = args.get('account_name') or args.get('client_name')
                if found_name:
                    self.account_name = found_name
            except: pass
            
            self.sow_sent = True # Mark that we attempted to send
            friendly_status = f"📝 Generating PDF for {self.account_name}..."
            self.update_status(friendly_status)

        elif "Get Opportunity Details" in tool_name:
            self.update_status("🔍 Reading Salesforce Data...")
        elif "Get Opportunity Line Items" in tool_name:
            self.update_status("📦 Analyzing Products...")
        else:
            self.update_status(f"🛠️ Executing: {tool_name}...")
        
        self.log(f"Using tool: {tool_name}")

    def on_tool_end(self, output, **kwargs):
        # --- NEW DEBUG LINE ---
        # Convert output to string just in case it's an object
        print(f"🔥 DEBUG: RAW TOOL OUTPUT: {str(output)}") 
        # ----------------------

        # Existing logic
        if "Envelope ID:" in output:
            match = re.search(r"Envelope ID:\s*([a-fA-F0-9\-]+)", output)
            if match:
                env_id = match.group(1)
                print(f"✅ CAPTURED ENVELOPE ID: {env_id}")
                self.save_envelope_id(env_id)
            else:
                print(f"❌ Regex failed to match inside: {output}")

    def on_agent_action(self, action, **kwargs):
        thought = action.log.split('Action:')[0].replace("Thought:", "").strip()
        if thought:
            self.log(f"🤔 Thought: {thought}")
            if "draft" in thought.lower() or "prepare" in thought.lower():
                self.update_status(f"✍️ Drafting SOW content for {self.account_name}...")

    def on_chain_end(self, outputs, **kwargs):
        if 'output' in outputs:
            self.log("🏁 Task process finished.")
            # If we sent the SOW, add to the success list
            if self.sow_sent:
                self.mark_deal_complete()
                self.update_status(f"✅ SOW Sent to {self.account_name}!")

@app.route('/', methods=['GET'])
def index():
    """Renders the main UI page with a list of opportunities."""
    from tools import get_open_opportunities
    print("--- [UI] Page requested. Calling get_open_opportunities tool. ---")

    opportunities = [] # Default to an empty list
    try:
        # 1. Get the raw JSON string from the tool
        opportunities_json = get_open_opportunities()
        print(f"--- [UI] Raw JSON received from tool: {opportunities_json} ---")

        # 2. Check if the received data is a valid-looking JSON array (after stripping whitespace)
        if opportunities_json and opportunities_json.strip().startswith('['):
            # 3. Parse the JSON into a Python list
            opportunities = json.loads(opportunities_json)
            print(f"--- [UI] Successfully parsed JSON. Found {len(opportunities)} opportunities. ---")
        else:
            print("--- [UI] Data received from tool was not a valid JSON array. Passing empty list to UI. ---")

    except Exception as e:
        print(f"❌ ERROR in index route: {type(e).__name__} - {e}")

    # --- NEW: Get the Salesforce Base URL ---
    # This ensures links work even if your domain changes
    sf_base_url = os.getenv("SALESFORCE_INSTANCE_URL")

    print("--- [UI] Rendering template... ---")
    return render_template('index.html', opportunities=opportunities,sf_base_url=sf_base_url)

@app.route('/start-closing', methods=['POST'])
def start_closing():
    """Receives Opp IDs, creates a task, starts agents, and returns a task ID."""
    opportunity_ids = request.form.getlist('opportunity_ids')

    # Check if the toggle was checked (returns 'on' if checked, None if not)
    use_docgen = request.form.get('use_docgen') == 'on'

    if not opportunity_ids:
        return jsonify({"status": "error", "message": "No opportunities selected."}), 400

    task_id = str(uuid.uuid4())
    with tasks_lock:
        # tasks[task_id] = {"total": len(opportunity_ids), "completed": 0, "status": "running"}
        # NEW: Initialize an empty 'logs' list
        tasks[task_id] = {
            "total": len(opportunity_ids), 
            "completed": 0, 
            "status": "running",
            "logs": [],
            "current_step": "🚀 Spooling up AI Agents...",
            "finished_deals": [], # <--- NEW LIST TO TRACK COMPLETIONS
            "results": {}
        }

    #template_id = "8cbe3647-6fce-49fb-877a-7911cf278316"

    # You might have two different template IDs now:
    # 1. The PDF/Legal Combo Template
    # 2. The DocGen Word Template
    if use_docgen:
        template_id = "dba32743-cb50-42d1-beec-abd6a2d91a70" 
    else:
        template_id = "8cbe3647-6fce-49fb-877a-7911cf278316"

    signer_role = "ClientSigner"

    for opp_id in opportunity_ids:
        print(f"Queueing deal process for Opportunity: {opp_id}")
        # Create a handler specific to this Opportunity
        log_handler = AgentLogHandler(task_id, opp_id)
        # Pass the task_id to the background thread
        thread = threading.Thread(target=start_deal_process, args=(opp_id, template_id, signer_role, task_id, tasks, tasks_lock, log_handler, use_docgen))
        thread.start()

    return jsonify({"status": "started", "task_id": task_id})

@app.route('/webhook', methods=['POST'])
def docusign_webhook():
    """Listens for incoming webhook events from DocuSign Connect."""
    xml_data = request.data
    print(f"--- Raw webhook data received: {xml_data} ---")
    
    try:
        data = json.loads(xml_data)
        
        # 1. Extract Envelope Details
        # 'data' is the top level key in the JSON structure you provided earlier
        envelope_data = data.get('data', {})
        envelope_id = envelope_data.get('envelopeId')
        
        # Status might be in envelopeSummary or directly in data
        envelope_summary = envelope_data.get('envelopeSummary', {})
        envelope_status = envelope_summary.get('status') or envelope_data.get('status')

        # 2. Extract Custom Field (Opportunity ID)
        opportunity_id = None
        
        # Strategy A: Check directly under 'data' (Common in JSON mode)
        custom_fields = envelope_data.get('customFields', {}).get('textCustomFields', [])
        
        # Strategy B: Check inside 'envelopeSummary' (Legacy mode)
        if not custom_fields:
            custom_fields = envelope_summary.get('customFields', {}).get('textCustomFields', [])

        # Loop through fields to find the ID
        for field in custom_fields:
            if field.get('name') == 'opportunity_id':
                opportunity_id = field.get('value')
                break

        print(f"✅ Webhook received: Envelope {envelope_id} | OppID {opportunity_id} | Status '{envelope_status}'")
        
        if envelope_status == 'completed' and opportunity_id:
            print(f"🚀 Triggering agent to finalize deal for Opp ID {opportunity_id}...")
            thread = threading.Thread(target=finalize_deal, args=(envelope_id, opportunity_id))
            thread.start()
        elif not opportunity_id:
            print("⚠️ Warning: Opportunity ID not found in webhook payload.")
            
    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        
    return Response(status=200)
@app.route('/update-contact', methods=['POST'])
def update_contact():
    """Receives a contact ID and new email and updates it in Salesforce."""
    data = request.get_json()
    contact_id = data.get('contact_id')
    new_email = data.get('new_email')

    if not contact_id or not new_email:
        return jsonify({"status": "error", "message": "Missing contact_id or new_email."}), 400

    # Create the JSON string input for the tool
    tool_input = json.dumps({"contact_id": contact_id, "new_email": new_email})

    # Call the tool
    result = update_contact_email(tool_input)

    if "Successfully" in result:
        return jsonify({"status": "success", "message": result})
    else:
        return jsonify({"status": "error", "message": result}), 500
    
@app.route('/task-status/<task_id>', methods=['GET'])
def task_status(task_id):
    """Checks the status of a background task."""
    with tasks_lock:
        task = tasks.get(task_id, {})
    return jsonify(task)

# listener.py (Updated classify_intent)

def classify_intent(user_message):
    """
    Uses the LLM to both REPLY to the user and DECIDE on an action.
    """
    
    prompt = f"""
    You are a helpful, intelligent Sales Operations Assistant for GenWatt Inc.
    Your goal is to help users manage Salesforce Opportunities and generate SOWs.

    Analyze the user's message: "{user_message}"

    Return a JSON object with two keys: "intent" and "response".

    RULES FOR 'INTENT':
    1. If the user asks to see, list, show, or find opportunities/projects:
       Set "intent" to "FETCH_DATA".
    
    2. If the user explicitly asks to generate SOWs, send envelopes, or "close" the selected deals:
       Set "intent" to "EXECUTE_CLOSING".
    
    3. For ANY other conversation (greetings, questions about your capabilities, general help):
       Set "intent" to "GENERAL_CHAT".

    RULES FOR 'RESPONSE':
    - If intent is FETCH_DATA: Write a brief confirmation like "Sure, let me pull up the current open opportunities for you."
    - If intent is EXECUTE_CLOSING: Write a confirmation like "Understood. I will start the SOW generation process for the selected deals immediately."
    - If intent is GENERAL_CHAT: **GENERATE A REAL, HELPFUL AI RESPONSE.** Answer their question, introduce yourself, or explain that you can help them generate SOWs and manage deals. Be conversational and professional.

    Output ONLY valid JSON.
    """
    
    try:
        # We use the same LLM instance configured in this file
        result = llm.invoke(prompt)
        content = result.content.strip()
        
        # Clean up potential markdown formatting from the LLM
        if content.startswith("```json"): 
            content = content[7:]
        if content.endswith("```"): 
            content = content[:-3]
            
        return json.loads(content.strip())
        
    except Exception as e:
        print(f"Intent classification failed: {e}")
        return {
            "intent": "GENERAL_CHAT", 
            "response": "I apologize, but I'm having trouble connecting to my brain right now. You can try asking me to 'Show opportunities'."
        }
    
@app.route('/agent-chat', methods=['POST'])
def agent_chat():
    data = request.get_json()
    user_message = data.get('message', '')
    # The frontend sends selected IDs if the table is visible
    selected_ids = data.get('selected_ids', []) 
    
    # 1. Decide what to do
    decision = classify_intent(user_message)
    intent = decision.get('intent')
    bot_response = decision.get('response')

    response_payload = {
        "message": bot_response,
        "action": "none",
        "data": None
    }

    # 2. Handle "Show Projects"
    if intent == "FETCH_DATA":
        from tools import get_open_opportunities
        opps_json = get_open_opportunities()
        # Send the data back to the frontend to render the table
        response_payload["action"] = "render_table"
        response_payload["data"] = json.loads(opps_json)

    # 3. Handle "Execute Closing"
    elif intent == "EXECUTE_CLOSING":
        if not selected_ids:
            response_payload["message"] = "I can do that, but you haven't selected any projects yet. Please ask me to 'Show projects', select the ones you want, and then ask me to close them."
        else:
            # Trigger the exact same logic as the button click
            # We reuse the code from /start-closing but call it internally
            task_id = str(uuid.uuid4())
            with tasks_lock:
                tasks[task_id] = {
                    "total": len(selected_ids), 
                    "completed": 0, 
                    "status": "running",
                    "logs": [],
                    "current_step": "🚀 Agent triggered via Chat...",
                    "finished_deals": [],
                    "results": {}
                }

            # Configure Template ID (Defaulting to DocGen)
            template_id = "a1b2c3d4-e5f6-7890-abcd-1234567890ab" # Your DocGen GUID
            signer_role = "ClientSigner"

            for opp_id in selected_ids:
                log_handler = AgentLogHandler(task_id, opp_id)
                thread = threading.Thread(
                    target=start_deal_process, 
                    args=(opp_id, template_id, signer_role, task_id, tasks, tasks_lock, log_handler, True) # True for use_docgen
                )
                thread.start()
            
            response_payload["action"] = "start_polling"
            response_payload["task_id"] = task_id

    return jsonify(response_payload)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)