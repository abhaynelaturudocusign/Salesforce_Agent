# main.py - Refactored for Webhooks
import os
from langchain_openai import AzureChatOpenAI
from langchain.agents import AgentExecutor, Tool, create_react_agent
from langchain.prompts import PromptTemplate
from tools import *  # Import all tools

# --- AGENT SETUP (This part remains mostly the same) ---
llm = AzureChatOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    temperature=0)

tools = [
    Tool(
        name="Get Opportunity Details", 
        func=get_opportunity_details, 
        description="Use this to fetch key details for a Salesforce Opportunity. The input should be a single Salesforce Opportunity ID."
    ),
    Tool(
        name="Create and Send DocuSign from Template", 
        func=create_and_send_docusign_from_template, 
        description=("Use this to create and send a DocuSign envelope from a template. The input MUST be a valid JSON string with the following four keys: 'recipient_name', 'recipient_email', 'template_id', and 'signer_role_name'.")
    ),
    Tool(
        name="Get DocuSign Envelope Status", 
        func=get_docusign_envelope_status, 
        description="Use this to check the current status of a DocuSign envelope. The input should be a single DocuSign envelope_id."
    ),
    # --- NEW COMBINED TOOL ---
    Tool(
        name="Download and Attach DocuSign Document to Salesforce",
        func=download_and_attach_document_to_salesforce,
        description="Use this to download a signed document from DocuSign and attach it to a Salesforce Opportunity. The input must be a JSON string with 'envelope_id', 'record_id', and 'file_name'."
    ),
    Tool(
        name="Update Opportunity Stage", 
        func=update_opportunity_stage, 
        description="Use this to update the stage of a Salesforce Opportunity. The input must be a JSON string with 'opportunity_id' and 'new_stage'."
    )
] # Note: I've abbreviated the descriptions for brevity. Use your full descriptions.

template = """
Answer the following questions as best you can. You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought:{agent_scratchpad}
"""
prompt = PromptTemplate.from_template(template)
agent = create_react_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent,
                               tools=tools,
                               verbose=True,
                               handle_parsing_errors=True)


# --- REFACTORED LOGIC ---
def start_deal_process(opportunity_id, template_id, signer_role):
    """Initiates the process by sending the contract."""
    print("🚀 Starting the deal process...")
    goal = f"""
    First, get the details for Salesforce Opportunity ID '{opportunity_id}' to find the primary contact.
    Then, send the contract to them using DocuSign template ID '{template_id}' and signer role '{signer_role}'.
    Report the outcome and the new Envelope ID.
    """
    result = agent_executor.invoke({"input": goal})
    print(f"✅ Initiation complete: {result['output']}")


def finalize_deal(envelope_id):
    """Called by the webhook listener to finalize the deal."""
    print(f"🚀 Finalizing deal for completed envelope {envelope_id}...")
    
    opportunity_id = "006dM00000FSckrQAD" # The Opportunity ID you've been using

    # --- UPDATED GOAL ---
    goal = f"""
    The document with DocuSign Envelope ID '{envelope_id}' has been signed.
    Finalize the deal for Salesforce Opportunity ID '{opportunity_id}'.
    1. Download the signed document from DocuSign and attach it to the Salesforce Opportunity. Name the file 'Signed_Contract.pdf'.
    2. Update the Opportunity's stage to 'Closed Won'.
    """
    result = agent_executor.invoke({"input": goal})
    print(f"✅ Finalization complete: {result['output']}")


if __name__ == "__main__":
    # This file is now used to KICK OFF the process.
    # The listener.py will handle the completion.

    opportunity_id = "006dM00000FSckrQAD"
    template_id = "e6e01c3e-6545-4a50-947e-9035fe2e243b"
    signer_role = "Signer"

    start_deal_process(opportunity_id, template_id, signer_role)
