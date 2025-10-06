# listener.py
import os
from flask import Flask, request, Response
import xmltodict
import threading

# Import the agent's finalize function from your main.py file
# We will create this function in the next step.
from main import finalize_deal

app = Flask(__name__)


@app.route('/webhook', methods=['POST'])
def docusign_webhook():
    """
    Listens for incoming webhook events from DocuSign Connect.
    """
    # Get the raw XML data from the request
    xml_data = request.data

    try:
        # Convert the XML to a Python dictionary
        data = xmltodict.parse(xml_data)
        envelope_status = data['DocuSignEnvelopeInformation'][
            'EnvelopeStatus']['Status']
        envelope_id = data['DocuSignEnvelopeInformation']['EnvelopeStatus'][
            'EnvelopeID']

        print(
            f"✅ Webhook received: Envelope {envelope_id} has status '{envelope_status}'"
        )

        # If the envelope is completed, trigger the agent's finalization logic
        if envelope_status == 'Completed':
            print(
                f"🚀 Triggering agent to finalize deal for envelope {envelope_id}..."
            )
            # Run the agent logic in a background thread so we can respond to DocuSign immediately
            thread = threading.Thread(target=finalize_deal,
                                      args=(envelope_id, ))
            thread.start()

    except Exception as e:
        print(f"❌ Error processing webhook: {e}")

    # Respond to DocuSign immediately with a 200 OK to acknowledge receipt
    return Response(status=200)


def run_listener():
    # Runs the Flask app. Replit will automatically detect this and expose a public URL.
    app.run(host='0.0.0.0', port=8080)


if __name__ == "__main__":
    run_listener()
