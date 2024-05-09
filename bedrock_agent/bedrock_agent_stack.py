from aws_cdk import (
    Duration,
    Stack,
    aws_s3 as s3,
    aws_glue_alpha as glue_l2,
    aws_glue as glue,
    aws_iam as iam,
    aws_lambda as lambda_,
)
from constructs import Construct
from aws_cdk.aws_lambda_python_alpha import PythonFunction

class BedrockAgentStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a bucket that will have the data files
        # Create the input bucket based on the region
        raw_data_bucket_name = f"raw-data-{self.region}-{self.account}"
        raw_data_bucket = s3.Bucket(
            self, 
            "RawDataBucket", 
            bucket_name=raw_data_bucket_name
        )

        # Or read the parameter for the bucket name from the parameter store
        # Adding the read permission the S3 bucket for the LLM few shot examples
        # raw_data_bucket_name = ssm.StringParameter.value_for_string_parameter(
        #     self, 
        #     "/bedrock-agent/input-bucket-name"
        # )
        # raw_data_bucket = s3.Bucket.from_bucket_name(
        #     self, 
        #     "RawDataBucket", 
        #     bucket_name=raw_data_bucket_name
        # )

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
        athena_results_bucket_name = f"aws-athena-query-results-{self.account}-{self.region}"
        athena_results_bucket = s3.Bucket(
            self, "AthenaResultsBucket", 
            bucket_name=athena_results_bucket_name
        )

        # Creating the lambda function that will be called by the agent

        # The execution role for the lambda
        lambda_role = iam.Role(
            self,
            "LambdaAgentRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # Adding permissions to call Glue and Athena
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:DeleteTable",
                    "glue:CreateTable",
                ],
                resources=[
                    f"arn:aws:glue:{self.region}:{self.account}:catalog",
                    f"arn:aws:glue:{self.region}:{self.account}:database/{glue_database.database_name}",
                    f"arn:aws:glue:{self.region}:{self.account}:table/{glue_database.database_name}/*",
                ],
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StopQueryExecution",
                    "athena:GetWorkGroup",
                ],
                resources=["*"]
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetBucketLocation"
                ],
                resources=[
                     "arn:aws:s3:::*"
                ],
            )
        )

        # Powertools Lambda Layer
        powertools_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            id="lambda-powertools",
            # At the moment we wrote this example, the aws_lambda_python_alpha CDK constructor is in Alpha, o we use layer to make the example simpler
            # See https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_lambda_python_alpha/README.html
            # Check all Powertools layers versions here: https://docs.powertools.aws.dev/lambda-python/latest/#lambda-layer
            layer_version_arn=f"arn:aws:lambda:{self.region}:017000801446:layer:AWSLambdaPowertoolsPythonV2:58"
        )

        # AWS Wrangler Lambda Layer
        # The list of ARN is available here: https://aws-sdk-pandas.readthedocs.io/en/latest/layers.html
        wrangler_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            id="lambda-wrangler",
            layer_version_arn=f"arn:aws:lambda:{self.region}:336392948345:layer:AWSSDKPandas-Python312:8"
        )

        action_group_function = PythonFunction(
            self,
            "BedrockAgentActionLambdaFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            function_name="BedrockAgentActionLambda",
            description="A lambda function to handle agent actions",
            layers=[
                powertools_layer,
                wrangler_layer
            ],
            entry="./lambda",  
            index="bedrock_agent_lambda.py",
            handler="lambda_handler",
            role=lambda_role,
            environment={
                "DATABASE_NAME": glue_database.database_name,
                "ATHENA_RESULTS_BUCKET": athena_results_bucket.bucket_name
            },
            # The timeout can cause failure for large queries.
            timeout=Duration.seconds(30),
            memory_size=512,
        )

        athena_results_bucket.grant_read_write(action_group_function)
        raw_data_bucket.grant_read(action_group_function)