import boto3
import json
import urllib.request
from urllib.error import URLError

def handler(event, context):
    # S3 bucket name
    bucket_name = event['ResourceProperties']['BucketName']
    
    # GitHub repository details
    repo_owner = 'guyernest'
    repo_name = 'bedrock-agent'
    branch = 'master'
    path = 'sample-data'
    
    # GitHub API URL to get the contents of the directory
    api_url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}?ref={branch}'
    
    s3 = boto3.client('s3')
    
    def process_directory(url, s3_prefix):
        try:
            with urllib.request.urlopen(url) as response:
                files_str = response.read().decode()
                files = json.loads(files_str)
                
            for file in files:
                if file['type'] == 'file':
                    # Download the file content
                    file_url = file['download_url']
                    with urllib.request.urlopen(file_url) as response:
                        file_content = response.read()
                    
                    # Upload the file to S3
                    s3_key = f'{s3_prefix}/{file["name"]}'
                    s3.put_object(Bucket=bucket_name, Key=s3_key, Body=file_content)
                elif file['type'] == 'dir':
                    # Recursively process subdirectories
                    process_directory(file['_links']['self'], f'{s3_prefix}/{file["name"]}')
        except URLError as e:
            print(f"Error accessing GitHub API: {e}")
            raise
        except Exception as e:
            print(f"Error: {e}")
            raise

    process_directory(api_url, 'data')

    return {
        'PhysicalResourceId': 'GitHubToS3Copy',
        'Data': {
            'Message': f'Successfully copied files to s3://{bucket_name}/data/'
        }
    }