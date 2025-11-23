# main.py
import os
from langchain_openai import AzureChatOpenAI
from langchain.agents import AgentExecutor, Tool, create_react_agent
from langchain.prompts import PromptTemplate
from tools import * # Import all tools

# --- AGENT SETUP (This is the core agent configuration) ---
llm = AzureChatOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    temperature=0
)

tools = [
    Tool(name="Get Opportunity Details", func=get_opportunity_details, description="..."),
    Tool(name="Create and Send DocuSign from Template", func=create_and_send_docusign_from_template, description="..."),
    Tool(name="Download and Attach DocuSign Document to Salesforce", func=download_and_attach_document_to_salesforce, description="..."),
    Tool(name="Update Opportunity Stage", func=update_opportunity_stage, description="..."),
    Tool(name="Get Line Items", func=get_opportunity_line_items, description="Gets product line items."),
    Tool(name="Create Composite SOW", func=create_composite_sow_envelope, description="Generates and sends an SOW. Input must comprise client details and a 'pdf_data' object containing scope, background, and milestones.")
] # Note: Abbreviated descriptions for brevity. Use your full descriptions.

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
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)


# --- AGENT WORKER FUNCTIONS ---
def start_deal_process(opportunity_id, template_id, signer_role_name, task_id, tasks, tasks_lock):
    """Initiates the process by sending the contract."""
    print(f"🚀 Starting the deal process for Opportunity {opportunity_id}...")
    
    goal = f"""
    Act as a Solution Architect for Opportunity '{opportunity_id}'.
    
    1. GATHER DATA:
       - Get Opportunity details to find the 'Primary Contact Name' and 'Primary Contact Email'.
       - Get Opportunity Line Items (Products, Prices).
    
    2. DRAFT CONTENT:
       - Write a 2-sentence "Background" on why the client needs this project.
       - Write 3 "Objectives" based on the products being sold.
       - Summarize the Line Items into a list of "Scope Items".
       - Format the Line Items into a JSON list of "Milestones" (Name, Date, Amount).
    
    3. EXECUTE:
       Use the 'Create Composite SOW' tool.
       - 'client_name': Use the Primary Contact Name found in step 1.
       - 'client_email': Use the Primary Contact Email found in step 1.
       - 'project_name': Use the Opportunity Name.
       - 'static_legal_template_id': '{template_id}'
       - 'opportunity_id': '{opportunity_id}'
       - 'signer_role_name': '{signer_role_name}'
       - 'pdf_data': Construct a dictionary with the content you drafted (background_text, objectives_text, scope_items, milestones).
       
    Report the final Envelope ID.
    """

    try:
        result = agent_executor.invoke({"input": goal})
        print(f"✅ Initiation complete for Opp {opportunity_id}: {result['output']}")
    except Exception as e:
        print(f"❌ Error processing Opp {opportunity_id}: {e}")
    finally:
        # This block runs whether the agent succeeds or fails
        with tasks_lock:
            if task_id in tasks:
                tasks[task_id]["completed"] += 1
                if tasks[task_id]["completed"] == tasks[task_id]["total"]:
                    tasks[task_id]["status"] = "completed"

def finalize_deal(envelope_id, opportunity_id):
    """Called by the webhook listener to finalize the deal."""
    print(f"🚀 Finalizing deal for completed envelope {envelope_id} and Opp {opportunity_id}...")
    goal = f"""
    The document with DocuSign Envelope ID '{envelope_id}' has been signed.
    Finalize the deal for Salesforce Opportunity ID '{opportunity_id}'.
    1. Download the signed document from DocuSign and attach it to the Salesforce Opportunity. Name the file 'Signed_Contract.pdf'.
    2. Update the Opportunity's stage to 'Closed Won'.
    """
    result = agent_executor.invoke({"input": goal})
    print(f"✅ Finalization complete for Opp {opportunity_id}: {result['output']}")