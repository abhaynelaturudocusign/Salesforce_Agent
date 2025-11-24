# listener.py
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
        self.prefix = f"[{opp_id}] "
    
    # Helper to update the "User Friendly" status
    def update_status(self, status_text):
        with tasks_lock:
            if self.task_id in tasks:
                # We store the latest "Human Readable" status here
                tasks[self.task_id]['current_step'] = status_text

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.log("🤖 Agent started.")
        self.update_status("🧠 Agent Initializing & Reading Instructions...")

    def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized['name']
        
        # --- INNOVATIVE STATUS MAPPING ---
        if "Get Opportunity Details" in tool_name:
            friendly_status = "🔍 Fetching Project & Client Details from Salesforce..."
        elif "Get Opportunity Line Items" in tool_name:
            friendly_status = "📦 Analyzing Product Line Items & Costs..."
        elif "Create Composite SOW" in tool_name:
            friendly_status = "📝 Generating PDF Scope & Merging Legal Terms..."
        else:
            friendly_status = f"🛠️ Using tool: {tool_name}..."
        
        self.log(f"Using tool: {tool_name}")
        self.update_status(friendly_status)

    def on_tool_end(self, output, **kwargs):
        self.log("Tool completed.")
        self.update_status("✅ Step Complete. Reasoning next steps...")

    def on_agent_action(self, action, **kwargs):
        thought = action.log.split('Action:')[0].strip()
        self.log(f"Thought: {thought}")
        # Only show the thought if it's short, otherwise generic
        if len(thought) < 50:
            self.update_status(f"🤔 {thought}...")
        else:
            self.update_status("🧠 Agent is drafting content...")

    def on_chain_end(self, outputs, **kwargs):
        self.log("Process finished.")
        self.update_status("🚀 SOW Sent! Waiting for next deal...")

    def log(self, message):
        with tasks_lock:
            if self.task_id in tasks:
                tasks[self.task_id]['logs'].append(self.prefix + message)

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
            "current_step": "🚀 Spooling up AI Agents..."
        }

    template_id = "8cbe3647-6fce-49fb-877a-7911cf278316"
    signer_role = "ClientSigner"

    for opp_id in opportunity_ids:
        print(f"Queueing deal process for Opportunity: {opp_id}")
        # Create a handler specific to this Opportunity
        log_handler = AgentLogHandler(task_id, opp_id)
        # Pass the task_id to the background thread
        thread = threading.Thread(target=start_deal_process, args=(opp_id, template_id, signer_role, task_id, tasks, tasks_lock, log_handler))
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

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)