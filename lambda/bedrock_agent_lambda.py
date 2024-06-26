from typing_extensions import Dict, List

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import BedrockAgentResolver
from aws_lambda_powertools.utilities.typing import LambdaContext

tracer = Tracer()
logger = Logger()
from aws_lambda_powertools.event_handler.exceptions import BadRequestError
 
app = BedrockAgentResolver()

import boto3
import os
outputLocation = os.environ['ATHENA_RESULTS_BUCKET']
database_name = os.environ['DATABASE_NAME']
glue_client = boto3.client('glue') 

import awswrangler as wr

@app.get("/getschema", description="Gets the schema of the database tables")
@tracer.capture_method
def get_schema() -> List:
    tables = (
        wr
        .catalog
        .tables(database=database_name)
        [["Table","Description","Columns"]]
        .to_dict('records')
    )
    return tables

@app.get("/querydatabase", description="Query the database with the given SQL query")  
@tracer.capture_method
def execute_athena_query(query):
    logger.info(f"SQL Query: {query}")
    df = None
    try:
        df = (
            wr
            .athena
            .read_sql_query(
                query, 
                database=database_name,
                ctas_approach=False,
            ).to_dict('records')
        )
    except Exception as e:
        print(f"Error: {str(e)}")    
        raise BadRequestError(f"Error: {str(e)}")
    return df

@logger.inject_lambda_context
@tracer.capture_lambda_handler
def lambda_handler(event: dict, context: LambdaContext):
    return app.resolve(event, context)

if __name__ == "__main__":  
    print("Testing...")
    print(get_schema())
    print(execute_athena_query("Select * from hall_of_fame limit 1"))
    print(app.get_openapi_json_schema()) 