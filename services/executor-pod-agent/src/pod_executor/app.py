"""FastAPI application for pod-based agent executor."""

from fastapi import FastAPI
from ark_sdk.executor_app import ExecutorApp
from .executor import PodAgentExecutor

# Create the executor and app
executor = PodAgentExecutor()
app_instance = ExecutorApp(executor, "PodAgent")


def create_app() -> FastAPI:
    """Create and return the FastAPI application."""
    return app_instance.create_app()
