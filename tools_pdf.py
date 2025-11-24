# tools_pdf.py
import os
import re
from jinja2 import Environment, BaseLoader
from weasyprint import HTML, CSS

SECTION_3_TEXT = """
<p><strong>(a) Key Attributes</strong></p>
<ul>
    <li>Highly effective resources: Consultant will understand Project requirements and deploy qualified personnel.</li>
    <li>Demonstrate flexibility: Consultant will be flexible in adjusting implementation methods.</li>
</ul>
<p><strong>(b) General Consultant Responsibilities</strong></p>
<ul>
    <li>Comply with and fulfill its responsibilities outlined in this Work Order.</li>
    <li>Assign senior level personnel as a central point of contact.</li>
</ul>
"""

def generate_scope_and_milestones_pdf(data_dictionary):
    """
    Generates the SOW PDF.
    """
    
    # --- HELPER: Calculate Total ---
    # We calculate the total here in Python to ensure accuracy
    total_val = 0.0
    milestones = data_dictionary.get('milestones', [])
    for m in milestones:
        try:
            # Remove '$' and ',' to turn "$1,500.00" into float(1500.00)
            clean_amount = re.sub(r'[^\d.]', '', str(m.get('amount', '0')))
            total_val += float(clean_amount)
        except: pass
    
    # Format total back to string
    total_formatted = f"${total_val:,.2f}"
    
    # Pass total to template
    data_dictionary['calculated_total'] = total_formatted

    # 1. HTML Template
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { font-family: 'Helvetica', sans-serif; font-size: 10pt; line-height: 1.4; padding: 40px; }
            
            /* --- UPDATED HEADER STYLE (Goal 2) --- */
            .header-block { 
                text-align: center; 
                font-weight: bold; 
                font-size: 24pt; /* Increased size (like H1) */
                margin-bottom: 30px; 
                border-bottom: 2px solid #333; 
                padding-bottom: 15px; 
                text-transform: uppercase;
            }
            
            h2 { font-size: 12pt; font-weight: bold; margin-top: 20px; border-bottom: 1px solid #ccc; text-transform: uppercase; }
            .label { font-weight: bold; width: 150px; display: inline-block; }
            .section-content { margin-bottom: 15px; }
            .page-break { page-break-before: always; }
            
            /* Table Styling */
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #000; padding: 6px; vertical-align: top; }
            th { background-color: #f2f2f2; }
            
            /* Total Row Style */
            .total-row td { font-weight: bold; background-color: #eef; }
            
            .hidden-anchor { color: #ffffff; font-size: 1px; }
        </style>
    </head>
    <body>

        <div class="header-block">
            WORK ORDER FOR:<br/>
            {{ account_name }} </div>

        <h2>1. Project Basics</h2>
        <div><span class="label">Client Contact:</span> {{ client_name }}</div>
        <div><span class="label">Start Date:</span> {{ start_date }}</div>
        <div><span class="label">End Date:</span> {{ end_date }}</div>

        <h2>2. Background & Objectives</h2>
        <div class="section-content">
            <p><strong>Background:</strong> {{ background_text }}</p>
            <p><strong>Objectives:</strong> {{ objectives_text }}</p>
        </div>

        <h2>3. Consultant Key Attributes</h2>
        <div class="section-content">
            {{ section_3_static_content }}
        </div>

        <h2>4. Scope & Deliverables</h2>
        <div class="section-content">
            <ul>
            {% for item in scope_items %}
                <li><strong>{{ item.title }}:</strong> {{ item.description }}</li>
            {% endfor %}
            </ul>
        </div>

        <h2 class="page-break">9. Milestone Obligations</h2>
        <table>
            <thead>
                <tr>
                    <th>Milestone / Product</th>
                    <th>Description</th>
                    <th>Date</th>
                    <th>Amount</th>
                </tr>
            </thead>
            <tbody>
                {% for m in milestones %}
                <tr>
                    <td>{{ m.name }}</td>
                    <td>{{ m.description }}</td>
                    <td>{{ m.date }}</td>
                    <td>{{ m.amount }}</td>
                </tr>
                {% endfor %}
                <tr class="total-row">
                    <td colspan="3" style="text-align: right;">TOTAL:</td>
                    <td>{{ calculated_total }}</td>
                </tr>
            </tbody>
        </table>

        <div style="margin-top:50px;">
            <span class="hidden-anchor">\\s1\\</span>
        </div>

    </body>
    </html>
    """

    rtemplate = Environment(loader=BaseLoader()).from_string(html_template)
    
    data_dictionary['section_3_static_content'] = SECTION_3_TEXT
    
    # Ensure account_name defaults if missing
    if 'account_name' not in data_dictionary:
        data_dictionary['account_name'] = data_dictionary.get('client_name', 'Client')

    html_content = rtemplate.render(data_dictionary)
    
    if not os.path.exists('generated_docs'):
        os.makedirs('generated_docs')

    # Sanitize filename
    safe_name = "".join(x for x in data_dictionary['project_name'] if x.isalnum() or x in "._- ")
    filename = f"generated_docs/SOW_{safe_name.replace(' ', '_')}.pdf"
    
    HTML(string=html_content).write_pdf(filename)
    
    return filename