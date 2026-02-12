"""Pod-based agent execution logic."""

import asyncio
import json
import logging
from typing import List, Dict, Any
from kubernetes_asyncio import client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.rest import ApiException
from ark_sdk.executor import BaseExecutor, ExecutionEngineRequest, Message
from ark_sdk.k8s import get_namespace, init_k8s
import time

logger = logging.getLogger(__name__)


class PodAgentExecutor(BaseExecutor):
    """Executes agents by spawning Kubernetes pods/jobs."""

    def __init__(self):
        super().__init__("PodAgent")
        self.namespace = get_namespace()
        self.job_timeout = 1800  # 30 minutes default timeout
        logger.info(f"PodAgentExecutor initialized for namespace: {self.namespace}")

    async def execute_agent(self, request: ExecutionEngineRequest) -> List[Message]:
        """Execute agent by spawning a Kubernetes Job."""
        try:
            # Initialize Kubernetes async client
            await init_k8s()

            logger.info(f"Spawning pod for agent {request.agent.name}")

            # Create unique job name
            timestamp = str(int(time.time()))
            job_name = f"{request.agent.name}-{timestamp}"[:63]  # K8s name limit

            # Create the job
            job = await self._create_agent_job(job_name, request)

            # Wait for job completion
            result_messages = await self._wait_for_job_completion(job_name)

            # Cleanup job
            await self._cleanup_job(job_name)

            return result_messages

        except Exception as e:
            logger.error(f"Pod agent execution failed: {e}", exc_info=True)
            error_msg = Message(
                role="assistant",
                content=f"Error: Pod agent execution failed: {str(e)}",
                name=request.agent.name,
            )
            return [error_msg]

    async def _create_agent_job(
        self, job_name: str, request: ExecutionEngineRequest
    ) -> client.V1Job:
        """Create a Kubernetes Job for agent execution."""
        # Prepare request data as JSON
        request_json = json.dumps({
            "agent": request.agent.model_dump(),
            "userInput": request.userInput.model_dump(),
            "history": [msg.model_dump() for msg in request.history],
            "tools": [tool.model_dump() for tool in request.tools],
        })

        # Get agent image from parameters or use default
        agent_image = "claude-sdk:local"
        api_key_secret = None
        anthropic_base_url = None
        for param in request.agent.parameters:
            if param.name == "podAgentImage":
                agent_image = param.value
            elif param.name == "apiKeySecret":
                api_key_secret = param.value
            elif param.name == "anthropicBaseUrl":
                anthropic_base_url = param.value
        logger.info(f"Using agent image: {agent_image}")
        logger.info(f"Using Anthropic base URL: {anthropic_base_url}")

        # Build environment variables
        # Extract user input - try different approaches
        logger.info(f"=== DEBUG REQUEST ===")
        logger.info(f"Request type: {type(request)}")
        logger.info(f"Request dict: {request.__dict__ if hasattr(request, '__dict__') else 'no __dict__'}")
        logger.info(f"UserInput type: {type(request.userInput)}")
        logger.info(f"UserInput: {request.userInput}")

        # Try to get content
        user_input_content = ""
        if hasattr(request.userInput, 'content'):
            user_input_content = request.userInput.content
            logger.info(f"Got content from userInput.content: {user_input_content[:100]}")
        elif hasattr(request, 'userInput') and isinstance(request.userInput, dict):
            user_input_content = request.userInput.get('content', '')
            logger.info(f"Got content from userInput dict: {user_input_content[:100]}")
        else:
            user_input_content = str(request.userInput)
            logger.info(f"Converted userInput to string: {user_input_content[:100]}")

        env_vars = [
            client.V1EnvVar(name="ARK_USER_INPUT", value=user_input_content),
            client.V1EnvVar(name="HOME", value="/home/agent"),
            client.V1EnvVar(
                name="PATH",
                value="/app/node_modules/.bin:/usr/local/bin:/usr/bin:/bin",
            ),
        ]

        # Pass agent parameters
        logger.info(f"Agent parameters: {request.agent.parameters}")
        for param in request.agent.parameters:
            env_var_name = f"ARK_PARAM_{param.name.upper()}"
            env_vars.append(client.V1EnvVar(name=env_var_name, value=param.value))

        # Add model configuration from agent config
        if request.agent.model.config:
            azure_config = request.agent.model.config.get("azure", {})
            if azure_config:
                env_vars.append(
                    client.V1EnvVar(
                        name="ANTHROPIC_BASE_URL",
                        value=azure_config.get("azure_endpoint", ""),
                    )
                )

        # Add Anthropic base URL if specified
        if anthropic_base_url:
            env_vars.append(
                client.V1EnvVar(name="ANTHROPIC_BASE_URL", value=anthropic_base_url)
            )

        # Add API key from secret if specified
        if api_key_secret:
            env_vars.append(
                client.V1EnvVar(
                    name="ANTHROPIC_API_KEY",
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=api_key_secret, key="ANTHROPIC_API_KEY"
                        )
                    ),
                )
            )

        # Define pod template
        container = client.V1Container(
            name="agent",
            image=agent_image,
            image_pull_policy="IfNotPresent",
            command=["bun", "run", "dist/entrypoint.js"],
            env=env_vars,
            resources=client.V1ResourceRequirements(
                requests={"memory": "512Mi", "cpu": "500m"},
                limits={"memory": "2Gi", "cpu": "2000m"},
            ),
            security_context=client.V1SecurityContext(
                run_as_user=1000,
                run_as_group=1000,
                allow_privilege_escalation=False,
            ),
        )

        # Pod template spec
        pod_template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={"app": "pod-agent", "job-name": job_name}
            ),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[container],
                security_context=client.V1PodSecurityContext(fs_group=1000),
            ),
        )

        # Job spec
        job_spec = client.V1JobSpec(
            template=pod_template,
            backoff_limit=0,  # Don't retry failed jobs
            ttl_seconds_after_finished=300,  # Cleanup after 5 minutes
        )

        # Job object
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name),
            spec=job_spec,
        )

        # Create the job
        async with ApiClient() as api:
            batch_v1 = client.BatchV1Api(api)
            created_job = await batch_v1.create_namespaced_job(
                namespace=self.namespace, body=job
            )
            logger.info(f"Created job: {job_name}")
            return created_job

    async def _wait_for_job_completion(self, job_name: str) -> List[Message]:
        """Wait for job to complete and collect output."""
        async with ApiClient() as api:
            batch_v1 = client.BatchV1Api(api)
            core_v1 = client.CoreV1Api(api)

            start_time = time.time()
            while True:
                # Check timeout
                if time.time() - start_time > self.job_timeout:
                    raise TimeoutError(
                        f"Job {job_name} did not complete within {self.job_timeout}s"
                    )

                # Get job status
                job = await batch_v1.read_namespaced_job_status(
                    name=job_name, namespace=self.namespace
                )

                if job.status.succeeded:
                    logger.info(f"Job {job_name} succeeded")
                    # Get pod logs
                    return await self._get_job_output(job_name, core_v1)

                if job.status.failed:
                    logger.error(f"Job {job_name} failed")
                    # Try to get logs anyway
                    try:
                        messages = await self._get_job_output(job_name, core_v1)
                        return messages
                    except Exception as e:
                        logger.error(f"Could not get logs from failed job: {e}")
                        raise RuntimeError(f"Job {job_name} failed")

                # Wait before checking again
                await asyncio.sleep(2)

    async def _get_job_output(
        self, job_name: str, core_v1: client.CoreV1Api
    ) -> List[Message]:
        """Extract agent output from pod logs."""
        # Find pod for this job
        pods = await core_v1.list_namespaced_pod(
            namespace=self.namespace, label_selector=f"job-name={job_name}"
        )

        if not pods.items:
            raise RuntimeError(f"No pods found for job {job_name}")

        pod_name = pods.items[0].metadata.name
        logger.info(f"Getting logs from pod: {pod_name}")

        # Get pod logs
        logs = await core_v1.read_namespaced_pod_log(
            name=pod_name, namespace=self.namespace
        )

        # Parse output - expecting JSONL format with final result
        # Look for lines with {"type": "result", "content": "..."}
        messages = []
        for line in logs.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "result":
                    # Extract message from result
                    content = event.get("content", "")
                    if content:
                        messages.append(Message(role="assistant", content=content))
            except json.JSONDecodeError:
                # Not JSON, might be debug output - skip
                continue

        if not messages:
            # Fallback: treat entire log as message if no structured output
            logger.warning(
                f"No structured output found, using raw logs from pod {pod_name}"
            )
            messages.append(Message(role="assistant", content=logs))

        return messages

    async def _cleanup_job(self, job_name: str) -> None:
        """Delete the job after completion."""
        try:
            async with ApiClient() as api:
                batch_v1 = client.BatchV1Api(api)
                await batch_v1.delete_namespaced_job(
                    name=job_name,
                    namespace=self.namespace,
                    propagation_policy="Foreground",
                )
                logger.info(f"Deleted job: {job_name}")
        except ApiException as e:
            logger.warning(f"Could not delete job {job_name}: {e}")
