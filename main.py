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
    Tool(name="Update Opportunity Stage", func=update_opportunity_stage, description="...")
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
    First, get the details for Salesforce Opportunity ID '{opportunity_id}' to find the primary contact.
    Then, send the contract to them using the "Create and Send DocuSign from Template" tool.
    Ensure you provide all required parameters to the tool, including:
    - a 'template_id' of '{template_id}'
    - a 'signer_role_name' of '{signer_role_name}'
    - and the 'opportunity_id' which is '{opportunity_id}'.
    Report the outcome and the new Envelope ID.
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