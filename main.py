# main.py
import os
from langchain_openai import AzureChatOpenAI
from langchain.agents import AgentExecutor, Tool, create_react_agent
from langchain.prompts import PromptTemplate
from tools import * # Import all tools
from tools import search_history_for_chat

# --- AGENT SETUP (This is the core agent configuration) ---
# --- 1. SHARED LLM SETUP ---
llm = AzureChatOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    temperature=0
)

# ==============================================================================
#  AGENT 1: THE WORKER (Execution Engine)
#  Used by: start_deal_process, finalize_deal
# ==============================================================================

# Full Toolset for doing the work

tools = [
    Tool(name="Get Opportunity Details", func=get_opportunity_details, description="..."),
    Tool(name="Create and Send DocuSign from Template", func=create_and_send_docusign_from_template, description="..."),
    Tool(name="Download and Attach DocuSign Document to Salesforce", func=download_and_attach_document_to_salesforce, description="..."),
    Tool(name="Update Opportunity Stage", func=update_opportunity_stage, description="..."),
    Tool(name="Get Line Items", func=get_opportunity_line_items, description="Gets product line items."),
    Tool(name="Create Composite SOW", func=create_composite_sow_envelope, description="Generates and sends an SOW. Input must comprise client details and a 'pdf_data' object containing scope, background, and milestones."),
    # --- Tool B: The DocGen Word Generator ---
    Tool(
        name="Create DocGen SOW", 
        func=create_docgen_sow_envelope, 
        description="Generates an SOW using a WORD TEMPLATE (DocGen). Use this if asked for 'DocGen' or 'Word'."
    )
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

# --- NEW: Conversational Agent Tools ---
# We give the chat agent access to "Read" data, but not "Write" (Close deals)
chat_tools = [
    Tool(
        name="Fetch Open Projects",
        func=get_open_opportunities,
        description="Use this when the user wants to see a list of active, open, or new opportunities/projects."
    ),
    Tool(
        name="Search History",
        func=search_history_for_chat, # <--- Make sure this is imported from tools.py
        description="Use this to find information about PAST, CLOSED, or SENT deals. Useful for questions like 'Did we send to United Oil?' or 'Get me the link for Acme'."
    )
]

# --- NEW: The Autonomous Chat Agent ---
chat_template = """
You are 'The Closer', a smart Sales Operations Assistant.

You have access to the following tools:
{tools}

**INSTRUCTIONS:**
1. **Reasoning:** Always think about if you need a tool.
2. **Chatting:** If the user input is just a greeting ("Hi", "Thanks", "nothing"), DO NOT try to use a tool. Just reply conversationally.
3. **Format:**
   - If you use a tool, use the standard Format (Action/Action Input).
   - If you just want to reply to the user, YOU MUST USE THE FORMAT: "Final Answer: [Your text here]".

**CRITICAL:** If you do not use "Final Answer:", the system will crash.

FORMAT:
Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (repeat Thought/Action/Observation as needed)
Thought: I now know the final answer
Final Answer: [TAG IF NEEDED] The final response to the user.

Begin!

Question: {input}
Thought:{agent_scratchpad}
"""

chat_prompt = PromptTemplate.from_template(chat_template)
chat_agent_executor = AgentExecutor(
    agent=create_react_agent(llm, chat_tools, chat_prompt),
    tools=chat_tools,
    verbose=True,
    handle_parsing_errors=True
)

def handle_chat_interaction(user_message):
    """
    Fully autonomous agent handling.
    Returns: { "response": "...", "action": "..." }
    """
    print(f"🧠 Agent pondering: {user_message}")
    
    try:
        # The Agent does the thinking now. We don't write if/else statements.
        response = chat_agent_executor.invoke({"input": user_message})
        final_text = response['output']
        
        # Parse the Agent's decision tags
        action = "none"
        clean_text = final_text
        
        if "[RENDER_TABLE]" in final_text:
            action = "render_table"
            clean_text = final_text.replace("[RENDER_TABLE]", "").strip()
            # If the agent fetched data, we need to re-fetch it for the UI 
            # (Or, ideally, the tool returns it, but for now we re-fetch to keep it simple)
            data_payload = get_open_opportunities() 
        
        elif "[TRIGGER_CLOSING]" in final_text:
            action = "trigger_closing"
            clean_text = final_text.replace("[TRIGGER_CLOSING]", "").strip()
            data_payload = None
        
        else:
            # It's just a chat response (e.g. "Here is the link for United Oil...")
            data_payload = None

        return {
            "response": clean_text,
            "action": action,
            "data": json.loads(data_payload) if action == "render_table" else None
        }

    except Exception as e:
        print(f"Agent Error: {e}")
        return {"response": "I encountered an error processing your request.", "action": "none"}

# --- AGENT WORKER FUNCTIONS ---
def start_deal_process(opportunity_id, template_id, signer_role_name, task_id, tasks, tasks_lock, log_handler, use_docgen):
    """Initiates the process by sending the contract."""
    print(f"🚀 Starting the deal process for Opportunity {opportunity_id} (Task: {task_id})...")
    
    # --- DYNAMIC PROMPT GENERATION ---
    
    if use_docgen:
        # --- PATH A: DOCGEN (WORD) ---
        goal = f"""
        Act as a Solution Architect for Opportunity '{opportunity_id}'.
        
        1. GATHER DATA:
           - Get Opportunity details (Contact Name, Email, Account Name).
           - Get Opportunity Line Items.
        
        2. PREPARE CONTENT:
           - Calculate 'total_fixed_fee' (sum of items).
           - Draft 'background_text' and 'objectives_text'.
           - Create 'Project_Scope' and 'Project_Assumptions' lists.
        
        3. EXECUTE:
           **CRITICAL:** You MUST use the tool named 'Create DocGen SOW'. 
           
           Format the input JSON exactly like this, using the specific Template ID provided below:
           {{
               "client_name": "...",
               "client_email": "...",
               "account_name": "...",
               "project_name": "...",
               "template_id": "{template_id}",  <-- THIS INJECTS YOUR REAL GUID
               "signer_role_name": "{signer_role_name}",
               "opportunity_id": "{opportunity_id}",
               "total_fixed_fee": "...",
               "pdf_data": {{
                   "project_background": "...", 
                   "project_start_date": "...",
                   "project_end_date": "...",
                   "consultant_key_attributes": "...",
                   "Project_Scope": [ {{ "Delivery_of_product": "..." }} ],
                   "Project_Assumptions": [ 
                       {{ 
                           "Milestone_Product": "...", 
                           "Milestone_Description": "...",
                           "Milestone_Date": "...", 
                           "Milestone_Amount": "..."
                       }}
                   ]
               }}
           }}
        """
    else:
        # --- PROMPT FOR COMPOSITE PDF TOOL (UPDATED WITH YOUR NEW INSTRUCTIONS) ---
        goal = f"""
        Act as a Solution Architect for Opportunity '{opportunity_id}'.
        Your job is to write a professional Statement of Work (SOW) for Opportunity '{opportunity_id}'
        
        1. GATHER DATA:
           - Get Opportunity details (Contact Name, Contact Email). PAY ATTENTION to the 'Industry' and 'Opp_Description'.
           - Get Opportunity Line Items (Products, Prices, Dates).
        
        2. ARCHITECT THE CONTENT (BE CREATIVE):
           - Calculate 'total_fixed_fee' by summing the TotalPrice of all line items. Format as "5000.00" (no symbols).
    
           - **Background:** Write a professional 3-sentence executive summary. You must connect the client's Industry (found in step 1) to the specific need for power generation. Use the 'Opp_Description' for specific context.
    
           - **Objectives:** Write 3 strategic objectives. (e.g., "Ensure business continuity during grid outages").
    
           - GENERATE SCOPE ITEMS:
             Create a list of scope items, one for each product line item.
            - **Detailed Scope (The "Expander"):** For EACH product line item, do not just list the name. Write a full sentence describing the implementation work.
             * Example Input: "GenWatt 100kW"
             * Expected Output: "Delivery, installation, and electrical integration of one GenWatt 100kW unit, including site acceptance testing."
    
            - **Assumptions (NEW):** Generate 3 logical project assumptions based on the products sold (e.g., site access, permits, network connectivity).
    
           - GENERATE MILESTONES (CRITICAL RULE):
             Do NOT summarize the milestones into a single payment.
             You MUST create a specific Milestone entry for EVERY SINGLE Line Item found.
             
             Logic:
             - If you found 3 line items in step 1, your 'milestones' list MUST contain 3 items.
             - For each item:
                 - 'name': Use the Product Name (e.g. "GenWatt 100kW").
                 - 'description': Brief description of delivery.
                 - 'date': Use the ServiceDate. If null, use "Upon Delivery".
                 - 'amount': Use the specific TotalPrice of THAT item (e.g. "$30,000").
        
        3. EXECUTE:
           Use the 'Create Composite SOW' tool.
           
           IMPORTANT: You must format the 'pdf_data' JSON exactly matching this structure and fill the milestones table please dont summarize the milestones table with one row and also please do not add extra rows and also please do not add random dates in milestones if you didn't receive any data please leave them blank:
           
           {{
               "client_name": "...",
               "client_email": "...",
               "account_name": "...",
               "project_name": "...",
               "static_legal_template_id": "{template_id}",
               "signer_role_name": "{signer_role_name}",
               "opportunity_id": "{opportunity_id}",
               "total_fixed_fee": "...",
               "pdf_data": {{
                   "background_text": "2 sentences on context...",
                   "objectives_text": "3 bullet points...",
                   "scope_items": [ 
                       {{ "title": "Product Name", "description": "YOUR EXPANDED AI-GENERATED DESCRIPTION HERE" }}
                    ],
                    "assumptions_list": [ "Assumption 1...", "Assumption 2...", "Assumption 3..." ],
                   "milestones": [
                       {{
                           "name": "Milestone 1", 
                           "date": "YYYY-MM-DD", 
                           "amount": "$1,000.00"
                       }}
                   ]
               }}
           }}
           
        Report the final Envelope ID.
        """

    try:
        # --- UPDATED LINE: Pass the callback handler ---
        result = agent_executor.invoke(
            {"input": goal},
            config={"callbacks": [log_handler]} # <--- Connects the agent to the frontend
        )
        print(f"✅ Initiation complete for Opp {opportunity_id}: {result['output']}")
    except Exception as e:
        print(f"❌ Error processing Opp {opportunity_id}: {e}")
        # Log error to frontend too
        log_handler.log(f"❌ ERROR: {e}")
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

# listener.py (Updated classify_intent)

def classify_intent(user_message):
    print(f"🧠 Processing user message: {user_message}")
    
    # 1. READ MEMORY: Get recent history to give the LLM context
    from tools import get_local_history
    history_context = get_local_history()
    # Truncate history if too long to save tokens
    if len(history_context) > 2000: history_context = history_context[:2000] + "...(truncated)"

    prompt = f"""
    You are 'The Closer', an intelligent Sales Operations Assistant for GenWatt Inc.
    
    Current SOW History (Context for you):
    {history_context}

    User Message: "{user_message}"

    YOUR GOAL:
    Determine the user's intent and provide a helpful response.

    ### VALID INTENTS (Choose One):
    1. "FETCH_OPEN" -> If user wants to see NEW/OPEN opportunities to work on.
    2. "FETCH_HISTORY" -> If user explicitly asks to see the FULL history TABLE.
    3. "EXECUTE_CLOSING" -> If user wants to generate/send/close deals.
    4. "GENERAL_CHAT" -> For everything else (Greetings, Questions about specific past deals, Jokes).

    ### RESPONSE GUIDELINES:
    - If "FETCH_OPEN": Say you will pull up the open projects from Salesforce.
    - If "EXECUTE_CLOSING": Confirm you are starting the agents.
    - If "GENERAL_CHAT": 
        - You are a helpful assistant.
        - **CRITICAL:** If the user asks about a specific past deal (e.g. "Did we send the SOW for United Oil?" or "Give me the link for Acme"), USE THE HISTORY CONTEXT provided above to answer them.
        - Provide the 'DocuSignLink' if they ask for it.
        - Be conversational.

    ### OUTPUT FORMAT:
    Return ONLY a JSON object: {{ "intent": "...", "response": "..." }}
    """
    
    try:
        result = llm.invoke(prompt)
        content = result.content.strip()
        if content.startswith("```json"): content = content[7:]
        if content.endswith("```"): content = content[:-3]
        return json.loads(content.strip())
    except Exception as e:
        print(f"Intent Logic Error: {e}")
        return {"intent": "GENERAL_CHAT", "response": "I'm having trouble accessing my memory right now."}