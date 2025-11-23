# tools_pdf.py
import os
from jinja2 import Environment, BaseLoader
from weasyprint import HTML, CSS

# Static text for Section 3 to keep the code clean
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
    Generates the 'Front Half' of the SOW (Sections 1-5 & 9), 
    ready to be merged with the 'Back Half' (Legal T&Cs).
    Input: A dictionary containing project_name, client_name, milestones, etc.
    """
    
    # 1. HTML Template (Sections 1, 2, 3, 4, 5, 9)
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { font-family: 'Helvetica', sans-serif; font-size: 10pt; line-height: 1.4; padding: 40px; }
            .header-block { text-align: center; font-weight: bold; margin-bottom: 30px; border-bottom: 2px solid #333; padding-bottom: 10px; }
            h2 { font-size: 12pt; font-weight: bold; margin-top: 20px; border-bottom: 1px solid #ccc; text-transform: uppercase; }
            .label { font-weight: bold; width: 150px; display: inline-block; }
            .section-content { margin-bottom: 15px; }
            
            /* Table Styling */
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #000; padding: 6px; vertical-align: top; }
            th { background-color: #f2f2f2; }
            
            /* Signature Anchor - Invisible text for DocuSign */
            .hidden-anchor { color: #ffffff; font-size: 1px; }
        </style>
    </head>
    <body>

        <div class="header-block">
            WORK ORDER FOR: {{ project_name }}<br/>
            {{ client_name }} AND {{ consultant_name }}
        </div>

        <h2>1. Project Basics</h2>
        <div><span class="label">Client:</span> {{ client_name }}</div>
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

        <h2>9. Milestone Obligations</h2>
        <table>
            <thead>
                <tr>
                    <th>Milestone</th>
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
            </tbody>
        </table>

        <div style="margin-top:50px;">
            <span class="hidden-anchor">\\SIGNATURES\\</span>
        </div>

    </body>
    </html>
    """

    # 2. Render HTML
    rtemplate = Environment(loader=BaseLoader()).from_string(html_template)
    
    # Inject static content
    data_dictionary['section_3_static_content'] = SECTION_3_TEXT
    data_dictionary['consultant_name'] = "My Company Inc." # Or get from env
    
    html_content = rtemplate.render(data_dictionary)
    
    # 3. Save as PDF
    # Create a 'generated_docs' folder if it doesn't exist
    if not os.path.exists('generated_docs'):
        os.makedirs('generated_docs')

    filename = f"generated_docs/SOW_{data_dictionary['project_name'].replace(' ', '_')}.pdf"
    HTML(string=html_content).write_pdf(filename)
    
    return filename