from aws_cdk import (
    # Duration,
    Stack,
    aws_s3 as s3,
    aws_glue_alpha as glue_l2,
    aws_glue as glue,
    aws_iam as iam,
)
from constructs import Construct

class BedrockAgentStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a bucket that will have the data files
        # Create the input bucket based on the region
        raw_data_bucket_name = f"raw-data-{Stack.of(self).region}-{Stack.of(self).account}"
        raw_data_bucket = s3.Bucket(
            self, "RawDataBucket", 
            bucket_name=raw_data_bucket_name
        )

        # Or read the parameter for the bucket name from the parameter store
        # Adding the read permission the S3 bucket for the LLM few shot examples
        # bucket_name = ssm.StringParameter.value_for_string_parameter(
        #     self, 
        #     "/bedrock-agent/input-bucket-name"
        # )
        # bucket = s3.Bucket.from_bucket_name(self, "ExampleBucket", bucket_name)
        # bucket.grant_read_write(backend_role)

        # Create Glue Database
        glue_database = glue_l2.Database(
            self, 
            "GlueDatabase",
            database_name="bedrock_agent"
        )

        glue_crawler_role = iam.Role(
            self,
            "GlueCrawlerRole",
            description = "Role for the AWS Glue Crawler",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole")
            ]
        )

        raw_data_bucket.grant_read(glue_crawler_role)

        # Create Glue Crawler
        glue_crawler = glue.CfnCrawler(
            self,
            "GlueCrawler",
            name="bedrock_agent_crawler",
            database_name=glue_database.database_name,
            role=glue_crawler_role.role_arn,
            targets={
                "s3Targets": [
                    {
                        "path": raw_data_bucket.bucket_name
                    }
                ]
            }
        )
        
        # Create a bucket that will have the results of the queries
        athena_results_bucket_name = f"aws-athena-query-results-{Stack.of(self).region}-{Stack.of(self).account}"
        athena_results_bucket = s3.Bucket(
            self, "AthenaResultsBucket", 
            bucket_name=athena_results_bucket_name
        )
