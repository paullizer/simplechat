# user_input_plugin.py
"""Interactive questions, scoped to a retained V2 local-agent execution."""

import logging

from semantic_kernel.functions import kernel_function
from azure.core.exceptions import AzureError

from agent_execution_context import current_agent_execution
from agent_interaction_contracts import agent_tool_call_id, UserInputError
from functions_appinsights import exception_log_fields, log_event, workflow_log_context
from functions_user_input import request_user_input


INTERACTIVE_INPUT_INSTRUCTIONS = (
    "When a missing fact genuinely prevents you from continuing, use "
    "UserInput.request_user_input rather than asking an unstructured question in the final reply. "
    "Collect all currently known missing facts in one question set, usually two to four. "
    "Use useful suggestions with a custom answer for open questions. Do not invent optional "
    "interviews, repeat answered questions, ask for secrets, or use answers as action approval."
)


def _log_refusal(error, cause=None):
    """Why a question could not be opened: its code, its rule and where it was raised.

    Every refusal reads the same to the person and ends the agent's answer, so without this
    record the conditions cannot be told apart. No part of the question is recorded.
    """
    frame = current_agent_execution()
    identity = getattr(frame, "identity", None)
    log_event(
        "[USER_INPUT] An agent's question to the user could not be opened.",
        level=logging.WARNING,
        extra={
            **workflow_log_context(conversation_id=getattr(identity, "conversation_id", None)),
            "stage": "user_input_request", "validation_code": error.code,
            "validation_rule": error.rule, "status_code": error.status_code,
            "tool_call_id_present": bool(agent_tool_call_id.get()),
            **exception_log_fields(cause if cause is not None else error),
        },
    )


class UserInputPlugin:
    @kernel_function(
        name="request_user_input",
        description=(
            "Ask only for facts needed to continue the user's task. Collect all currently missing facts "
            "(usually 2-4) in one request. specification is JSON with message, requested_schema "
            "(a flat object schema with primitive properties and required names), and ui_hints. "
            "For open suggestions use a string/string-array without enum and "
            'ui_hints.fields[name]={"input":"choices","allow_custom":true,'
            '"choices":[{"value":"...","label":"..."}]}. '
            "Use enum only for genuinely closed choices. Never ask for secrets or treat an answer as "
            "permission to execute an outgoing action. Do not ask what the user already answered."
        ),
    )
    def ask(self, specification: str) -> str:
        try:
            return request_user_input(specification, agent_tool_call_id.get())
        except UserInputError as error:
            _log_refusal(error)
            raise
        except (AzureError, ValueError, TypeError, PermissionError) as error:
            failure = UserInputError("input_unavailable", 503, rule="request_could_not_be_saved_or_normalized")
            _log_refusal(failure, cause=error)
            raise failure from error
