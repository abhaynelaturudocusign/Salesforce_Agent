# tools.py

import os
import base64
import json
import time
import requests  # <--- IMPORT REQUESTS
import datetime
from dotenv import load_dotenv
from docusign_esign import ApiClient, EnvelopesApi, EnvelopeDefinition, Document, Signer, SignHere, Tabs, Recipients, TemplateRole, TextCustomField, CustomFields, Tabs, Text, Number
from simple_salesforce import Salesforce
from docusign_esign import CompositeTemplate, ServerTemplate, InlineTemplate, Document
from tools_pdf import generate_scope_and_milestones_pdf # Import the new PDF tool
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

# --- TOOL DEFINITIONS ---

# --- ADD THIS NEW FUNCTION ---
def get_docusign_client():
    """
    Generates a fresh, authenticated DocuSign API client.
    This is called inside every tool to ensure the token is never expired.
    """

    print(f"--- 🔄 AUTHENTICATING: Requesting a fresh DocuSign token at {datetime.datetime.now()} ---")
    try:
        api_client = ApiClient()
        api_client.host = os.getenv("DOCUSIGN_HOST")
        api_client.oauth_host_name = "account-d.docusign.com"

        # Generate a new token
        token_response = api_client.request_jwt_user_token(
            client_id=os.getenv("DOCUSIGN_IK"),
            user_id=os.getenv("DOCUSIGN_USER_ID"),
            oauth_host_name="account-d.docusign.com",
            private_key_bytes=open("docusign_private.key").read(),
            expires_in=3600,
            scopes=["signature", "impersonation"]
        )
        
        # Attach the token to the client headers
        api_client.set_default_header("Authorization", "Bearer " + token_response.access_token)
        return api_client
        
    except Exception as e:
        print(f"❌ DocuSign Authentication Failed: {e}")
        return None

# tools.py (new tool)

def get_opportunity_line_items(opportunity_id: str) -> str:
    """Fetches the product line items for a Salesforce Opportunity."""
    print(f"--- Calling Tool: get_opportunity_line_items for {opportunity_id} ---")
    try:
        query = f"""
            SELECT Product2.Name, Quantity, UnitPrice, Description, ServiceDate 
            FROM OpportunityLineItem 
            WHERE OpportunityId = '{opportunity_id}'
        """
        result = sf.query(query)
        records = result.get('records', [])
        if not records:
            return "No line items found."
        return json.dumps(records)
    except Exception as e:
        return f"Salesforce API Error: {e}"

# tools.py

# tools.py

def create_composite_sow_envelope(tool_input: str) -> str:
    print(f"--- Calling Tool: create_composite_sow_envelope ---")
    
    api_client = get_docusign_client()
    if not api_client: return "Error: DocuSign Auth Failed"

    try:
        args = json.loads(tool_input)
        client_name = args.get('client_name')
        client_email = args.get('client_email')
        project_name = args.get('project_name')
        static_legal_template_id = args.get('static_legal_template_id')
        opportunity_id = args.get('opportunity_id', '')
        signer_role_name = args.get('signer_role_name', 'Signer')
        total_fixed_fee = args.get('total_fixed_fee', '0.00')

        # --- NEW: Get Account Name ---
        account_name = args.get('account_name', '')

        pdf_data = args.get('pdf_data', {})

        if not client_email or not client_name or not static_legal_template_id:
            return "Error: Missing required client details."

        # 1. Generate the Dynamic PDF
        pdf_data['client_name'] = client_name
        pdf_data['project_name'] = project_name
        dynamic_pdf_path = generate_scope_and_milestones_pdf(pdf_data)
        
        with open(dynamic_pdf_path, "rb") as file:
            dynamic_pdf_bytes = file.read()
        dynamic_doc_b64 = base64.b64encode(dynamic_pdf_bytes).decode("ascii")

        # ---------------------------------------------------------
        # PART A: COMPOSITE TEMPLATE 1 - The Generated PDF
        # ---------------------------------------------------------
        # Purpose: Just add the PDF document and ensure the signer can see it.
         

        doc_pdf = Document(
            document_base64=dynamic_doc_b64,
            name="Scope of Work",
            document_id="1",
            file_extension="pdf"
        )

        # Signer Definition for PDF (Access Only, No Tabs)
        signer_pdf = Signer(
            email=client_email,
            name=client_name,
            role_name=signer_role_name,
            recipient_id="1",
            routing_order="1"
        )

        inline_pdf = InlineTemplate(
            sequence="1",
            documents=[doc_pdf],
            recipients=Recipients(signers=[signer_pdf]) 
        )

        comp_template_pdf = CompositeTemplate(
            composite_template_id="1",
            inline_templates=[inline_pdf]
        )

        # ---------------------------------------------------------
        # PART B: COMPOSITE TEMPLATE 2 - The Legal Template
        # ---------------------------------------------------------
        # Purpose: Load the Legal Doc and apply the TABS (Total Fee).
        
        # Custom Fields
        opp_id_field = TextCustomField(name='opportunity_id', value=opportunity_id, show='false')
        custom_fields = CustomFields(text_custom_fields=[opp_id_field])
        tabs_list = []
        # 1. Define the Tabs (Text Tab for "Total_Fixed_Fee")
        fee_tab = Text(
            tab_label="Total_Fixed_Fee_Text", # Must match Template Label
            value=str(total_fixed_fee)
        )
        tabs_list.append(fee_tab)
        # Account Name Tab (NEW)
        if account_name:
            account_tab = Text(
                tab_label="Account_Label", # Must match DocuSign Template
                value=str(account_name)
            )
        tabs_list.append(account_tab)
        
        # 2. Signer Definition for Legal (WITH TABS)
        # DocuSign merges this with 'signer_pdf' because email/name/id match.
        signer_legal = Signer(
            email=client_email,
            name=client_name,
            role_name=signer_role_name,
            recipient_id="1",
            routing_order="1",
            tabs=Tabs(text_tabs=tabs_list) # <--- TABS GO HERE
        )

        # 3. Server Template (The Legal Doc Source)
        server_template = ServerTemplate(
            sequence="1",
            template_id=static_legal_template_id
        )

        # 4. Inline Template (The Recipient Overlay)
        inline_template_legal = InlineTemplate(
            sequence="2",
            recipients=Recipients(signers=[signer_legal]),
            custom_fields=custom_fields 
        )

        comp_template_legal = CompositeTemplate(
            composite_template_id="2",
            server_templates=[server_template],
            inline_templates=[inline_template_legal]
        )

        # ---------------------------------------------------------
        # PART C: BUILD ENVELOPE
        # ---------------------------------------------------------
        
        

        # Stack them: PDF first, Legal second
        envelope_def = EnvelopeDefinition(
            status="sent",
            email_subject=f"SOW for {project_name}",
            composite_templates=[comp_template_pdf, comp_template_legal] # Stacked List
            
        )

        # --- DEBUG PRINT ---
        print("\n" + "="*30)
        print("🔍 DEBUG: GENERATED DOCUSIGN PAYLOAD")
        try:
            payload = api_client.sanitize_for_serialization(envelope_def)
            print(json.dumps(payload, indent=2))
        except: pass
        print("="*30 + "\n")
        # -------------------

        # Send
        envelopes_api = EnvelopesApi(api_client)
        result = envelopes_api.create_envelope(os.getenv("DOCUSIGN_API_ACCOUNT_ID"), envelope_definition=envelope_def)
        
        return f"SOW Sent! Envelope ID: {result.envelope_id}"

    except Exception as e:
        print(f"DocuSign API Error Detail: {e}")
        return f"Error generating SOW: {e}"

def get_open_opportunities() -> str:
    """
    Fetches all Opportunities in 'Negotiation/Review', including:
    1. Basic Opportunity Details
    2. Primary Contact Details (Name, Email, ID for editing)
    3. Count of Product Line Items
    """
    print("--- Calling Tool: get_open_opportunities ---")
    try:
        # Updated Query: Fetches Contact Roles AND Line Items in one go
        query = """
            SELECT Id, Name, Amount, CloseDate, 
                   (SELECT Contact.Id, Contact.Name, Contact.Email 
                    FROM OpportunityContactRoles 
                    WHERE IsPrimary = true LIMIT 1),
                   (SELECT Id FROM OpportunityLineItems)
            FROM Opportunity 
            WHERE StageName != 'Closed Won' AND IsClosed = false 
            ORDER BY Amount DESC
        """
        result = sf.query(query)
        records = result.get('records', [])
        
        if not records:
            return "[]"

        for opp in records:
            # --- 1. Process Contact Info (For UI Display & Editing) ---
            contact_roles = opp.get('OpportunityContactRoles')
            if contact_roles and contact_roles['records']:
                contact = contact_roles['records'][0]['Contact']
                opp['PrimaryContactId'] = contact['Id']
                opp['PrimaryContactName'] = contact['Name']
                opp['PrimaryContactEmail'] = contact['Email']
            else:
                opp['PrimaryContactId'] = None
                opp['PrimaryContactName'] = 'N/A'
                opp['PrimaryContactEmail'] = 'N/A'
            
            # --- 2. Process Product Count (For UI Badge) ---
            line_items = opp.get('OpportunityLineItems')
            if line_items and line_items.get('records'):
                opp['ProductCount'] = len(line_items['records'])
            else:
                opp['ProductCount'] = 0

            # --- 3. Cleanup Nested Objects ---
            if 'OpportunityContactRoles' in opp: del opp['OpportunityContactRoles']
            if 'OpportunityLineItems' in opp: del opp['OpportunityLineItems']
            if 'attributes' in opp: del opp['attributes']
            
        return json.dumps(records)
    except Exception as e:
        return f"Salesforce API Error: {e}"

def get_opportunity_details(opportunity_id: str) -> str:
    """Fetches key details for a given Salesforce Opportunity ID..."""
    # Clean the input to remove any leading/trailing whitespace
    cleaned_id = opportunity_id.strip()

    print(
        f"--- Calling Tool: get_opportunity_details with cleaned ID {cleaned_id} ---"
    )
    try:
        query = f"""
            SELECT Name, Amount, StageName, Account.Name,
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

        # Extract Account Name
        account_name = record['Account']['Name'] if record['Account'] else "Unknown Account"

        contact_roles = record.get('OpportunityContactRoles')
        if not contact_roles or contact_roles['totalSize'] == 0:
            return f"Error: No Primary Contact found for Opportunity {record['Name']}"

        contact = contact_roles['records'][0]['Contact']
        details = (
            f"Opportunity Name: {record['Name']}, Account Name: {account_name}, Amount: {record['Amount']}, Stage: {record['StageName']}, "
            f"Primary Contact Name: {contact['Name']}, Primary Contact Email: {contact['Email']}"
        )
        return details
    except Exception as e:
        return f"Salesforce API Error: {e}"


def create_and_send_docusign_from_template(tool_input: str) -> str:
    """
    Creates and sends a DocuSign envelope from a template. The input must be a JSON string with 
    'recipient_name', 'recipient_email', 'template_id', 'signer_role_name', and 'opportunity_id'.
    """
    print(
        f"--- Calling Tool: create_and_send_docusign_from_template with input {tool_input} ---"
    )

    api_client = get_docusign_client()

    if not api_client:
        return "Error: DocuSign API client is not authenticated."

    try:
        # Parse the JSON string input into a Python dictionary
        args = json.loads(tool_input)
        recipient_name = args['recipient_name']
        recipient_email = args['recipient_email']
        template_id = args['template_id']
        signer_role_name = args['signer_role_name']
        opportunity_id = args['opportunity_id']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error: Invalid input format. Please provide a valid JSON string with all required keys. Details: {e}"

    # --- NEW LOGIC: Define the custom field ---
    opp_id_field = TextCustomField(
        name='opportunity_id',  # The name of the field
        required='true',
        show='false',          # Hide it from the signer
        value=opportunity_id   # The actual SFDC Opportunity ID
    )
    custom_fields = CustomFields(text_custom_fields=[opp_id_field])
    # --- END OF NEW LOGIC ---

    envelope_definition = EnvelopeDefinition(template_id=template_id,
                                             status="sent",custom_fields=custom_fields)
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
    api_client = get_docusign_client()
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


# tools.py (Final Version of the function)

def download_and_attach_document_to_salesforce(tool_input: str) -> str:
    """
    Downloads a signed document from a completed DocuSign envelope and attaches it directly
    to a Salesforce Opportunity record. The input must be a JSON string with the keys
    'envelope_id', 'record_id' (the Opportunity ID), and 'file_name'.
    """
    print(f"--- Calling Tool: download_and_attach_document_to_salesforce with input {tool_input} ---")
    api_client = get_docusign_client()
    if not api_client:
        return "Error: DocuSign API client is not authenticated."

    try:
        args = json.loads(tool_input)
        envelope_id = args['envelope_id']
        record_id = args['record_id']
        file_name = args['file_name']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error: Invalid input format. Details: {e}"

    try:
        # Step 1: Get the document content DIRECTLY from DocuSign as bytes
        envelopes_api = EnvelopesApi(api_client)
        # This API call returns the file content as a bytes object
        file_content_bytes = envelopes_api.get_document(
            account_id=os.getenv("DOCUSIGN_API_ACCOUNT_ID"),
            envelope_id=envelope_id,
            document_id="combined"
        )
        print(f"--- Document content received from DocuSign (type: {type(file_content_bytes)}) ---")

        # Step 2: Base64 encode the bytes and attach to Salesforce
        file_content_base64 = base64.b64encode(file_content_bytes).decode('utf-8')

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
        return f"An error occurred during the download/attach process: {type(e).__name__} - {e}"
def update_contact_email(tool_input: str) -> str:
    """Updates the email address for a specific Salesforce Contact. The input must be a JSON string with the keys 'contact_id' and 'new_email'."""
    print(f"--- Calling Tool: update_contact_email with input {tool_input} ---")
    try:
        args = json.loads(tool_input)
        contact_id = args['contact_id']
        new_email = args['new_email']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error: Invalid input format. Details: {e}"

    try:
        sf.Contact.update(contact_id, {'Email': new_email})
        return f"Successfully updated email for Contact {contact_id}."
    except Exception as e:
        return f"Salesforce API Error: {e}"