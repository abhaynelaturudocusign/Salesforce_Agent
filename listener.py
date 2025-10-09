# listener.py
import os
import json
from flask import Flask, request, Response, render_template, redirect, url_for
from tools import get_open_opportunities, update_contact_email
import xmltodict
import threading

# Import the agent functions from your main.py file
from main import start_deal_process, finalize_deal 
# Import the new tool from tools.py
from tools import get_open_opportunities

app = Flask(__name__)

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

    print("--- [UI] Rendering template... ---")
    return render_template('index.html', opportunities=opportunities)

@app.route('/start-closing', methods=['POST'])
def start_closing():
    """Receives the selected Opportunity IDs and triggers the agent for each."""
    opportunity_ids = request.form.getlist('opportunity_ids')
    
    # You can get these from a config file or the UI in a more advanced version
    template_id = "e6e01c3e-6545-4a50-947e-9035fe2e243b"
    signer_role = "Signer"

    for opp_id in opportunity_ids:
        print(f"Starting deal process for Opportunity: {opp_id}")
        # Run each agent process in a background thread
        thread = threading.Thread(target=start_deal_process, args=(opp_id, template_id, signer_role))
        thread.start()
        
    return redirect(url_for('index')) # Redirect back to the main page

@app.route('/webhook', methods=['POST'])
def docusign_webhook():
    """Listens for incoming webhook events from DocuSign Connect."""
    xml_data = request.data
    print(f"--- Raw webhook data received: {xml_data} ---")
    
    try:
        data = json.loads(xml_data)
        
        envelope_id = data['data']['envelopeId']
        envelope_status = data['data']['envelopeSummary']['status']

        opportunity_id = None
        custom_fields = data['data']['envelopeSummary'].get('customFields', {}).get('textCustomFields', [])
        for field in custom_fields:
            if field.get('name') == 'opportunity_id':
                opportunity_id = field.get('value')
                break

        print(f"✅ Webhook received: Envelope {envelope_id} | OppID {opportunity_id} | Status '{envelope_status}'")
        
        if envelope_status == 'completed' and opportunity_id:
            print(f"🚀 Triggering agent to finalize deal for Opp ID {opportunity_id}...")
            # Pass both IDs to the finalize function
            thread = threading.Thread(target=finalize_deal, args=(envelope_id, opportunity_id))
            thread.start()
            
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
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)