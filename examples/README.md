# Usage Examples

This directory contains minimal usage examples for the extensions.

## Capability Intelligence

### Basic Pipeline

```python
from capability_intelligence.pipeline import Pipeline
from capability_intelligence.resolver import Resolver
from capability_intelligence.negotiator import Negotiator
from capability_intelligence.executor import Executor
from capability_intelligence.interpreter import Interpreter
from capability_intelligence.feedback_store import FeedbackStore
from capability_intelligence.policy_engine import PolicyEngine, policy_environment_allowed
from capability_intelligence.models import Domain

# Pipeline components are typically wired automatically by the
# Hermes plugin. For standalone usage:

# See tests/ for complete examples.
```