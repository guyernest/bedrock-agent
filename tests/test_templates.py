import json
from jinja2 import Environment, FileSystemLoader
import pytest

# Configure Jinja2 environment
env = Environment(loader=FileSystemLoader('ui/templates'))

def render_template(template_name, context):
    template = env.get_template(template_name)
    return template.render(context)

def test_template_with_data():
    trace = [
        {
            "sql": "SELECT * FROM TABLE"
        },
        {
            "table": [{"player1_name": "Dwight Howard", "total_rebounds": 13184}]
        },
        {
            "table": [{'num_teams_over_100': 52}]
        },
        {
            "table": {'statusCode': 400, 'message': "Error: INVALID_CAST_ARGUMENT: Cannot cast '' to INT"}
        },
        {
            "table": []
        },
        {
            "table": {'database': 'bedrock_agent', 'tables': [] }
        }
    ]
    context = {
        "question": "question",
        "completion": "completion",
        "traces": trace
    }

    expected_output = """
<div class='user-message'>User: question</div>
<div class='bot-response'>Bot: completion</div>

<div class="default text-left font-sans text-sm font-medium hover:bg-gray-100">
SELECT * FROM TABLE

</div>

<div class="default text-left font-sans text-sm font-medium hover:bg-gray-100">


    
<table border="1">
    <thead>
        <tr>
            
                <th>player1_name</th>
            
                <th>total_rebounds</th>
            
        </tr>
    </thead>
    <tbody>
        
        <tr>
            
                <td>Dwight Howard</td>
            
                <td>13184</td>
            
        </tr>
        
    </tbody>
</table>
    

</div>

<div class="default text-left font-sans text-sm font-medium hover:bg-gray-100">


    
<table border="1">
    <thead>
        <tr>
            
                <th>num_teams_over_100</th>
            
        </tr>
    </thead>
    <tbody>
        
        <tr>
            
                <td>52</td>
            
        </tr>
        
    </tbody>
</table>
    

</div>

<div class="default text-left font-sans text-sm font-medium hover:bg-gray-100">


    
        Error: INVALID_CAST_ARGUMENT: Cannot cast '' to INT
    

</div>

<div class="default text-left font-sans text-sm font-medium hover:bg-gray-100">


</div>

<div class="default text-left font-sans text-sm font-medium hover:bg-gray-100">


    

</div>
    """
    output = render_template('conversation.html', context).strip()
    print(output)
    assert output == expected_output.strip()

if __name__ == "__main__":
    pytest.main()