from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    aws_s3 as s3,
    aws_glue_alpha as glue_l2,
    aws_glue as glue,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_ssm as ssm,
    aws_apprunner_alpha as apprunner,
    aws_logs as logs,
)
from constructs import Construct
from aws_cdk.aws_lambda_python_alpha import PythonFunction
from aws_cdk.custom_resources import AwsCustomResource, AwsCustomResourcePolicy, PhysicalResourceId, Provider
from aws_cdk.custom_resources import AwsSdkCall

from cdklabs.generative_ai_cdk_constructs.bedrock import (
    Agent,
    ApiSchema,
    BedrockFoundationModel,
    PromptType,
    PromptState, 
    PromptCreationMode,
)
import json
class BedrockAgentStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Part 1 : Data Layer (S3, Glue, Athena)

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
                        "path": f'{raw_data_bucket.bucket_name}/data'
                    }
                ]
            }
        )
        
        # Create a bucket that will have the results of the queries
        # This is the format of default bucket name for Athena
        athena_results_bucket_name = f"aws-athena-query-results-{self.account}-{self.region}"
        athena_results_bucket = s3.Bucket(
            self, "AthenaResultsBucket", 
            bucket_name=athena_results_bucket_name
        )

        # Adding custom resources to copy the data to S3 using a Lambda function and invoke

        # Create the Lambda function
        github_to_s3_function = PythonFunction(
            self, 
            'GitHubToS3Function',
            runtime=lambda_.Runtime.PYTHON_3_12,
            entry="./lambda",  
            index="copy_data_to_s3_cr.py",
            handler='handler',
            timeout=Duration.seconds(30),        
        )

        # Grant the Lambda function permissions to write to the S3 bucket
        raw_data_bucket.grant_write(github_to_s3_function)

        # Create the custom resource
        github_to_s3_copy = AwsCustomResource(
            self, 
            'GitHubToS3Copy',
            on_create=AwsSdkCall(
                service='Lambda',
                action='invoke',
                parameters={
                    'FunctionName': github_to_s3_function.function_name,
                    'Payload': json.dumps({
                        'ResourceProperties': {
                            'BucketName': raw_data_bucket.bucket_name
                        }
                    })
                },
                physical_resource_id=PhysicalResourceId.of('GitHubToS3Copy')
            ),
            policy=AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=['lambda:InvokeFunction'],
                    resources=[github_to_s3_function.function_arn]
                ),
            ])
        )

        # Adding custom resources to start the Glue Crawler

        start_glue_crawler_cr = AwsCustomResource(
            self,
            "StartGlueCrawler",
            on_create= AwsSdkCall(
                service="Glue",
                action="startCrawler",
                parameters={
                    "Name": glue_crawler.name
                },
                physical_resource_id = PhysicalResourceId.of(f'{self.artifact_id}'),
            ),
            policy= AwsCustomResourcePolicy.from_sdk_calls(
                resources= AwsCustomResourcePolicy.ANY_RESOURCE
            ),
        )

        # Part 2 : Creating the lambda function that will be called by the agent

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
                    "glue:GetPartitions",
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
            # log_retention=logs.RetentionDays.ONE_WEEK,
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

        # Part 3 : Creating the Bedrock Agent

        # Reading the content of the text files in the prompts directory
        instruction = open(f"./config/instruction.txt", "r").read()
        # orchestration = open(f"./config/orchestration.txt", "r").read()
        # post_processing = open(f"./config/post-processing.txt", "r").read()

        agent = Agent(
            self,
            "BedrockAgent",
            name="BedrockAgentForDataQuery",
            description=f"An agent for generating SQL to Athena database",
            foundation_model=BedrockFoundationModel.ANTHROPIC_CLAUDE_SONNET_V1_0,
            instruction=instruction,
            should_prepare_agent=True,
            alias_name="test",
            # prompt_override_configuration={
            #     "prompt_configurations": [
            #         {
            #             "promptType": PromptType.ORCHESTRATION,
            #             "basePromptTemplate": orchestration,
            #             "promptState": PromptState.ENABLED,
            #             "promptCreationMode": PromptCreationMode.OVERRIDDEN,
            #             "inferenceConfiguration": {
            #                 "temperature": 0.0,
            #                 "topP": 1,
            #                 "topK": 250,
            #                 "maximumLength": 2048,
            #                 "stopSequences": ['</function_call>', '</answer>', '</error>'],
            #             },
            #         },
            #         {
            #             "promptType": PromptType.POST_PROCESSING,
            #             "basePromptTemplate": post_processing,
            #             "promptState": PromptState.ENABLED,
            #             "promptCreationMode": PromptCreationMode.OVERRIDDEN,
            #             "inferenceConfiguration": {
            #                 "temperature": 0.0,
            #                 "topP": 1,
            #                 "topK": 250,
            #                 "maximumLength": 2048,
            #                 "stopSequences": ['/n/nHuman:'],
            #             },
            #         },
            #     ]
            # }
        )

        agent.add_action_group(
            action_group_name=f"SchemaAndQueryAnalyzer",
            description=f"Use these functions to query the Athena {glue_database.database_name} database",
            action_group_executor=action_group_function,
            action_group_state="ENABLED",
            api_schema=ApiSchema.from_asset(f"./config/openai-schema.json"),  
        )
        agent.add_action_group(
            action_group_name = "UserInputAction",
            action_group_state="ENABLED",
            parent_action_group_signature="AMAZON.UserInput"
        )

        # Part 4 : Creating the UI

        # alias = agent.add_alias(
        #     alias_name="test",
        #     agent_version="1"
        # )

        # Set the parameters of the agents for UI to read
        ssm.StringParameter(
            self, 
            "AgentIdParameter",
            parameter_name="/bedrock-agent-data/Bedrock-agent-id",
            description="Bedrock agent ID",
            string_value=agent.agent_id
        )

        ssm.StringParameter(
            self, 
            "AgentAliasIdParameter",
            parameter_name="/bedrock-agent-data/Bedrock-agent-alias-id",
            description="Bedrock agent alias ID",
            string_value=agent.alias_id
        )

        # Create the role for the UI backend
        ui_backend_role = iam.Role(self, "UI Backend Role",
            role_name=f"AppRunnerBedrockAgentUIRole-{self.region}",
            assumed_by=iam.ServicePrincipal("tasks.apprunner.amazonaws.com"),
        )

        # Adding the permission to write to the X-Ray Daemon
        ui_backend_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AWSXRayDaemonWriteAccess"
            )
        )

        # Adding the permission to read from the parameter store
        ui_backend_role.add_to_policy(iam.PolicyStatement(
            sid="ReadSSM",
            effect=iam.Effect.ALLOW,
            actions=[
                "ssm:GetParameter",
                "ssm:GetParameters",
                "ssm:GetParametersByPath",
            ],
            resources=[
                f"arn:aws:ssm:{self.region}:{self.account}:parameter/bedrock-agent-data/*"
            ]
        ))

        # Adding the permission to invoke the agent in Bedrock
        ui_backend_role.add_to_policy(iam.PolicyStatement(
            sid="InvokeBedrockAgent",
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:InvokeAgent",
            ],
            resources=[
                agent.agent_arn,
                agent.alias_arn
            ]
        ))
                
        github_connection_arn = ssm.StringParameter.value_for_string_parameter(
            self, 
            "/bedrock-agent-data/GitHubConnection"
        )

        repository_url = ssm.StringParameter.value_for_string_parameter(
            self, 
            "/bedrock-agent-data/GitHubRepositoryURL"
        )

        # Create the UI backend using App Runner
        ui_hosting_service = apprunner.Service(
            self, 
            'Service', 
            source=apprunner.Source.from_git_hub(
                configuration_source= apprunner.ConfigurationSourceType.REPOSITORY,
                repository_url= repository_url,
                branch= 'master',
                connection= apprunner.GitHubConnection.from_connection_arn(github_connection_arn),
            ),
            service_name= "bedrock-agent-chat-ui",
            auto_deployments_enabled= True,
            instance_role=ui_backend_role,
        )

        # Override the value of the SourceConfiguration.CodeRepository.SourceCodeVersion.
        # to the right value of "ui"
        ui_hosting_service.node.default_child.add_override(
            "Properties.SourceConfiguration.CodeRepository.SourceDirectory", 
            "ui"
        )

        # Output the bucket name for the raw data
        CfnOutput(self, "Raw Data Bucket", value=raw_data_bucket.bucket_name)

        # Output the name of the Glue Crawler 
        CfnOutput(self, "Glue Crawler", value=glue_crawler.name)

        # Output the URL of the UI
        CfnOutput(self, "UI URL", value=ui_hosting_service.service_url)

