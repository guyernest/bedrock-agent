
from typing import Annotated
from fastapi import FastAPI, Request, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import Depends
import json
import uvicorn
import boto3

# Get the region
app_runner = boto3.client('apprunner') 
region = app_runner.meta.region_name
# Get the account id
account_id = boto3.client('sts').get_caller_identity().get('Account') 

# Loading parameters from the parameter store
ssm = boto3.client('ssm')

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# prettyprint json in jinja
def ppjson(value, indent=2):
	return json.dumps(json.loads(value), indent=indent)

templates.env.filters['ppjson'] = ppjson

bedrock_agent_runtime_client = boto3.client('bedrock-agent-runtime')

@app.get("/use_case/questions", response_class=HTMLResponse, tags=['bedrock-agent'])
async def switch_use_case(request: Request):
    questions = [
         "What was John Denny's salary in 1986?",
         "What year was Nolan Ryan inducted into the Hall of Fame?",
         "Who is the richest player in the history of baseball?"
    ]
    return templates.TemplateResponse(
        "recommended_questions.html", 
        {
            "request": request,
            "questions": questions,
        }
    )


# Ask policy question on the org-shield directory
@app.post("/chat-about-baseball", response_class=HTMLResponse, tags=['bedrock-agent'])
async def ask_question(question: Annotated[str, Form()], request: Request):
    agent_id = ssm.get_parameter(Name=f'/bedrock-agent-data/Bedrock-agent-id')['Parameter']['Value']
    agent_alias_id = ssm.get_parameter(Name=f'/bedrock-agent-data/Bedrock-agent-alias-id')['Parameter']['Value']

    response = bedrock_agent_runtime_client.invoke_agent(
        agentAliasId=agent_alias_id,
        agentId=agent_id,
        inputText=question,
        enableTrace=False,
        sessionId="42",
    )
    completion = ""

    for event in response.get("completion"):
        chunk = event.get("chunk", {})
        completion = completion + chunk.get("bytes", b'').decode('utf-8')

    html_content = f"""
        <div class='user-message'>User: {question}</div>
        <div class='bot-response'>Bot: {completion}</div>
        """
    return HTMLResponse(content=html_content)

@app.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    context = {
        "request": request,
        "title": "Bedrock Agent Chat",
        "region": region,
        "account_id": account_id,
    }
    response = templates.TemplateResponse("chat.html", context)
    return response


favicon_path = 'static/favicon.ico'

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse(favicon_path)

import os
if __name__ == "__main__":
    print("Starting webserver...")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        log_level=os.getenv('LOG_LEVEL', "debug"),
        proxy_headers=True
    )
