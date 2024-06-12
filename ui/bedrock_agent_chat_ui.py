
from typing import Annotated
from fastapi import FastAPI, Request, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
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

bedrock_agent_runtime_client = boto3.client('bedrock-agent-runtime')
agent_id = ssm.get_parameter(Name='/bedrock-agent-data/Bedrock-agent-id')['Parameter']['Value']
agent_alias_id = ssm.get_parameter(Name='/bedrock-agent-data/Bedrock-agent-alias-id')['Parameter']['Value']


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

def extract_sql(trace_dict: dict) -> dict:
    trace = {}
    if trace_dict.get('orchestrationTrace', {}).get('invocationInput', {}).get('actionGroupInvocationInput', {}).get('apiPath') == '/querydatabase':
        parameters = trace_dict['orchestrationTrace']['invocationInput']['actionGroupInvocationInput'].get('parameters', [])
        for param in parameters:
            if param.get('name') == 'query':
                trace['sql']  = param.get('value')
    if trace_dict.get('orchestrationTrace', {}).get('observation', {}).get('actionGroupInvocationOutput', {}).get('text'):
        query_response = trace_dict['orchestrationTrace']['observation']['actionGroupInvocationOutput'].get('text', "{}")
        trace['table'] = json.loads(query_response)
    return trace

# Ask policy question on the org-shield directory
@app.post("/ask-question", response_class=HTMLResponse, tags=['bedrock-agent'])
async def ask_question(question: Annotated[str, Form()], request: Request):

    response = bedrock_agent_runtime_client.invoke_agent(
        agentAliasId=agent_alias_id,
        agentId=agent_id,
        inputText=question,
        enableTrace=True,
        sessionId="42",
    )
    completion = ""
    trace = []

    for event in response.get("completion"):
        chunk = event.get("chunk", {})
        completion = completion + chunk.get("bytes", b'').decode('utf-8')
        trace_chunk = event.get("trace", {}).get("trace", {})
        trace_chunk = extract_sql(trace_chunk)
        print(trace_chunk)
        if trace_chunk:
            trace.append(trace_chunk)

    context = {
        "request": request,
        "question": question,
        "completion": completion,
        "traces": trace
    }
    response = templates.TemplateResponse("conversation.html", context)

    return response

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
