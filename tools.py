# tools.py

import os
import json
import time
import requests  # <--- IMPORT REQUESTS
from dotenv import load_dotenv
from docusign_esign import ApiClient, EnvelopesApi, EnvelopeDefinition, Document, Signer, SignHere, Tabs, Recipients, TemplateRole
from simple_salesforce import Salesforce
# ... other imports ...

# Load environment variables from .env file
load_dotenv()

# --- AUTHENTICATION SETUP ---

# Create a session and disable SSL verification
session = requests.Session()
session.verify = False

# Suppress only the single InsecureRequestWarning from urllib3
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Salesforce Connection (now with the custom session)
sf = Salesforce(
    username=os.getenv("SALESFORCE_USERNAME"),
    password=os.getenv("SALESFORCE_PASSWORD"),
    security_token=os.getenv("SALESFORCE_SECURITY_TOKEN"),
    instance_url=os.getenv("SALESFORCE_INSTANCE_URL"),
    session=session  # <--- PASS THE MODIFIED SESSION
)

# DocuSign API Client Setup
# NOTE: This uses the JWT Grant authentication flow which is common for service integrations.
api_client = ApiClient()
api_client.host = os.getenv("DOCUSIGN_HOST")
api_client.oauth_host_name = "account-d.docusign.com"  # Use account.docusign.com for demo

try:
    # This function call performs the JWT authentication
    api_client.request_jwt_user_token(
        client_id=os.getenv("DOCUSIGN_IK"),
        user_id=os.getenv("DOCUSIGN_USER_ID"),
        oauth_host_name="account-d.docusign.com",
        private_key_bytes=open("docusign_private.key").read(),
        expires_in=3600,
        scopes=["signature", "impersonation"])
except Exception as e:
    print(f"DocuSign Auth Error: {e}")
    # Handle the error appropriately, maybe exit or raise
    api_client = None  # Ensure api_client is None if auth fails

# --- TOOL DEFINITIONS ---


def get_opportunity_details(opportunity_id: str) -> str:
    """Fetches key details for a given Salesforce Opportunity ID..."""
    # Clean the input to remove any leading/trailing whitespace
    cleaned_id = opportunity_id.strip()

    print(
        f"--- Calling Tool: get_opportunity_details with cleaned ID {cleaned_id} ---"
    )
    try:
        query = f"""
            SELECT Name, Amount, StageName, 
                   (SELECT Contact.Name, Contact.Email 
                    FROM OpportunityContactRoles 
                    WHERE IsPrimary = true LIMIT 1) 
            FROM Opportunity 
            WHERE Id = '{cleaned_id}'
        """
        result = sf.query(query)
        if result['totalSize'] == 0:
            return f"Error: No Opportunity found with ID {opportunity_id}"

        record = result['records'][0]
        contact_roles = record.get('OpportunityContactRoles')
        if not contact_roles or contact_roles['totalSize'] == 0:
            return f"Error: No Primary Contact found for Opportunity {record['Name']}"

        contact = contact_roles['records'][0]['Contact']
        details = (
            f"Opportunity Name: {record['Name']}, Amount: {record['Amount']}, Stage: {record['StageName']}, "
            f"Primary Contact Name: {contact['Name']}, Primary Contact Email: {contact['Email']}"
        )
        return details
    except Exception as e:
        return f"Salesforce API Error: {e}"


def create_and_send_docusign_from_template(tool_input: str) -> str:
    """
    Creates and sends a DocuSign envelope from a specific server template. 
    The input to this tool should be a JSON string with the keys 'recipient_name', 
    'recipient_email', 'template_id', and 'signer_role_name'.
    """
    print(
        f"--- Calling Tool: create_and_send_docusign_from_template with input {tool_input} ---"
    )
    if not api_client:
        return "Error: DocuSign API client is not authenticated."

    try:
        # Parse the JSON string input into a Python dictionary
        args = json.loads(tool_input)
        recipient_name = args['recipient_name']
        recipient_email = args['recipient_email']
        template_id = args['template_id']
        signer_role_name = args['signer_role_name']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error: Invalid input format. Please provide a valid JSON string with all required keys. Details: {e}"

    envelope_definition = EnvelopeDefinition(template_id=template_id,
                                             status="sent")
    signer = TemplateRole(email=recipient_email,
                          name=recipient_name,
                          role_name=signer_role_name)
    envelope_definition.template_roles = [signer]

    try:
        envelopes_api = EnvelopesApi(api_client)
        results = envelopes_api.create_envelope(
            account_id=os.getenv("DOCUSIGN_API_ACCOUNT_ID"),
            envelope_definition=envelope_definition)
        return f"Successfully sent envelope. Envelope ID is: {results.envelope_id}"
    except Exception as e:
        return f"DocuSign API Error: {e}"


def get_docusign_envelope_status(envelope_id: str) -> str:
    """Checks and returns the current status of a DocuSign envelope (e.g., 'sent', 'delivered', 'completed')."""
    print(
        f"--- Calling Tool: get_docusign_envelope_status for ID {envelope_id} ---"
    )
    if not api_client:
        return "Error: DocuSign API client is not authenticated."
    try:
        envelopes_api = EnvelopesApi(api_client)
        results = envelopes_api.get_envelope(
            account_id=os.getenv("DOCUSIGN_API_ACCOUNT_ID"),
            envelope_id=envelope_id)
        return f"Envelope status is: {results.status}"
    except Exception as e:
        return f"DocuSign API Error: {e}"


def update_opportunity_stage(tool_input: str) -> str:
    """
    Updates the stage of a Salesforce Opportunity to a new value. The input to this tool 
    should be a JSON string with the keys 'opportunity_id' and 'new_stage'.
    """
    print(
        f"--- Calling Tool: update_opportunity_stage with input {tool_input} ---"
    )
    try:
        # Parse the JSON string input into a Python dictionary
        args = json.loads(tool_input)
        opportunity_id = args['opportunity_id']
        new_stage = args['new_stage']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error: Invalid input format. Please provide a valid JSON string with 'opportunity_id' and 'new_stage'. Details: {e}"

    try:
        sf.Opportunity.update(opportunity_id.strip(),
                              {'StageName': new_stage.strip()})
        return f"Successfully updated Opportunity {opportunity_id} to {new_stage}."
    except Exception as e:
        return f"Salesforce API Error: {e}"


def download_docusign_document(tool_input: str) -> str:
    """
    Downloads the combined PDF of a completed DocuSign envelope and saves it as a temporary file.
    The input should be a JSON string with the key 'envelope_id'.
    Returns the local file path of the downloaded PDF.
    """
    print(
        f"--- Calling Tool: download_docusign_document with input {tool_input} ---"
    )
    if not api_client:
        return "Error: DocuSign API client is not authenticated."

    try:
        args = json.loads(tool_input)
        envelope_id = args['envelope_id']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error: Invalid input format. Please provide a valid JSON string with 'envelope_id'. Details: {e}"

    try:
        envelopes_api = EnvelopesApi(api_client)
        # "combined" is a special document_id to get the combined PDF of all documents
        temp_file_path = envelopes_api.get_document(
            account_id=os.getenv("DOCUSIGN_API_ACCOUNT_ID"),
            envelope_id=envelope_id,
            document_id="combined")
        return f"Successfully downloaded document to temporary path: {temp_file_path}"
    except Exception as e:
        return f"DocuSign API Error while downloading: {e}"


def attach_file_to_salesforce(tool_input: str) -> str:
    """
    Attaches a file to a Salesforce Opportunity record. The input should be a JSON string
    with the keys 'record_id' (the Opportunity ID), 'file_path' (the local path to the file),
    and 'file_name' (the desired name for the file in Salesforce).
    """
    print(
        f"--- Calling Tool: attach_file_to_salesforce with input {tool_input} ---"
    )

    try:
        args = json.loads(tool_input)
        record_id = args['record_id']
        file_path = args['file_path']
        file_name = args['file_name']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error: Invalid input format. Please provide a valid JSON string with all required keys. Details: {e}"

    try:
        with open(file_path, 'rb') as f:
            file_content_base64 = base64.b64encode(f.read()).decode('utf-8')

        content_version_data = {
            'Title': file_name,
            'PathOnClient': file_name,
            'VersionData': file_content_base64,
            'FirstPublishLocationId': record_id
        }

        result = sf.ContentVersion.create(content_version_data)

        if result.get('success'):
            return f"Successfully attached file '{file_name}' to Salesforce record {record_id}."
        else:
            errors = result.get('errors', 'Unknown error')
            return f"Salesforce API Error while attaching file: {errors}"

    except Exception as e:
        return f"An error occurred while attaching the file: {e}"
    finally:
        # IMPORTANT: Clean up the temporary file downloaded from DocuSign
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"--- Cleaned up temporary file: {file_path} ---")
