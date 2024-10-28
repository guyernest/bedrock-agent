import json
import sys
import numpy as np
from typing_extensions import Dict, List

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import BedrockAgentResolver
from aws_lambda_powertools.utilities.typing import LambdaContext

tracer = Tracer()
logger = Logger()
from aws_lambda_powertools.event_handler.exceptions import BadRequestError
 
app = BedrockAgentResolver()

import os
outputLocation = os.environ['ATHENA_RESULTS_BUCKET']
database_name = os.environ['DATABASE_NAME']

import awswrangler as wr

@app.get("/getschema", description="Gets the schema of the database tables")
@tracer.capture_method
def get_schema() -> Dict:
    # Fetch tables and descriptions
    tables_info = (
        wr
        .catalog
        .tables(database='bedrock_agent')
        [["Table", "Description"]]
    )
    
    # Initialize the JSON structure
    database_info = {"database": "bedrock_agent", "tables": []}
    
    # Iterate over each table to fetch column details
    for _, row in tables_info.iterrows():
        table_name = row["Table"]
        table_description = row["Description"]
        
        # Fetch column details
        columns_info = (
            wr
            .catalog
            .table(database="bedrock_agent", table=table_name)
            [["Column Name", "Type", "Comment"]]
        )
        
        # Add table and column details to the JSON structure
        table_info = {
            "Table": table_name,
            "Description": table_description,
            "Columns": []
        }
        
        for _, col_row in columns_info.iterrows():
            column_info = {
                "Column Name": col_row["Column Name"],
                "Type": col_row["Type"],
                "Comment": col_row["Comment"]
            }
            table_info["Columns"].append(column_info)
        
        database_info["tables"].append(table_info)
    
    return database_info

@app.get("/querydatabase", description="Query the database with the given SQL query")  
@tracer.capture_method
def execute_athena_query(query):
    logger.info(f"SQL Query: {query}")
    # Define the maximum size for the Lambda async response (25 MB)
    MAX_RESPONSE_SIZE = 25 * 1024  # 25 KB in bytes
    result = None
    try:
        df = (
            wr
            .athena
            .read_sql_query(
                query, 
                database=database_name,
                ctas_approach=False,
            )
        )
        # Calculate the size of the first row
        if not df.empty:
            first_row = df.iloc[0].to_dict()
            # Convert numpy.int64 to int to make it JSON serializable
            for key, value in first_row.items():
                if isinstance(value, np.int64):
                    first_row[key] = int(value)
            first_row_size = sys.getsizeof(json.dumps(first_row))
        else:
            first_row_size = 0
    
        # Estimate the maximum number of rows that can fit in the response
        if first_row_size > 0:
            max_rows = MAX_RESPONSE_SIZE // first_row_size
        else:
            max_rows = 0
    
        # Limit the DataFrame to the maximum number of rows
        limited_df = df.head(max_rows)
    
        # Convert the limited DataFrame to a dictionary
        result = limited_df.to_dict('records')
    except Exception as e:
        print(f"Error: {str(e)}")    
        raise BadRequestError(f"Error: {str(e)}")
    return result

@logger.inject_lambda_context
@tracer.capture_lambda_handler
def lambda_handler(event: dict, context: LambdaContext):
    return app.resolve(event, context)

if __name__ == "__main__":  
    print("Testing...")
    print(get_schema())
    print(execute_athena_query("Select * from hall_of_fame limit 1"))
    print(app.get_openapi_json_schema()) 