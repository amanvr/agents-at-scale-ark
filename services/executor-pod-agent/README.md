# Pod Agent Executor

Pod-based agent executor service for ARK. This execution engine spawns Kubernetes Jobs/Pods to execute agents, enabling true pod-based agent execution instead of in-process execution.

## Architecture

```
┌─────────────────┐
│  ARK Controller │
└────────┬────────┘
         │ HTTP POST /execute
         │ (agent config, input, history)
         ▼
┌─────────────────────────┐
│  Pod Executor Service   │
│  (This Service)         │
└────────┬────────────────┘
         │ kubectl create job
         ▼
┌─────────────────────────┐
│   Agent Pod             │
│   (claude-sdk, etc.)    │
└─────────────────────────┘
```

## Features

- Spawns Kubernetes Jobs for each agent execution
- Collects output from pod logs
- Automatic cleanup of completed jobs
- Timeout handling
- Structured JSONL output parsing

## Configuration

### Agent Labels

The executor reads configuration from agent labels:

- `pod-agent-image`: Container image to use (default: `claude-sdk:local`)
- `anthropic-api-key-secret`: Secret name containing `ANTHROPIC_API_KEY`

### Environment Variables

- `HOST`: Listen host (default: `0.0.0.0`)
- `PORT`: Listen port (default: `8000`)

## Development

```bash
# Install dependencies
uv pip install -e .

# Run locally (requires kubeconfig)
python -m pod_executor
```

## Deployment

See `chart/` directory for Helm deployment.
