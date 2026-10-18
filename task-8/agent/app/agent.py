"""Ядро агента: цикл LLM + tool-calling.

Режим (vulnerable/protected) выбирается из config.AGENT_MODE.
В защищённом режиме применяются input/output стражи и изолированный промпт.
"""
import json
import logging

from . import config
from . import llm
from . import policy
from . import guards
from . import tools_vulnerable
from . import tools_protected

logger = logging.getLogger("agent.core")


def _select_tools():
    if config.AGENT_MODE == "protected":
        return tools_protected.TOOL_SCHEMAS, tools_protected.dispatch
    return tools_vulnerable.TOOL_SCHEMAS, tools_vulnerable.dispatch


def _system_prompt():
    if config.AGENT_MODE == "protected":
        return policy.PROTECTED_SYSTEM_PROMPT
    return policy.VULNERABLE_SYSTEM_PROMPT


def run_agent(user_input: str, history: list = None):
    """Основной цикл агента.

    Возвращает dict: {response, mode, tools_used, blocked_by_input_guard,
                      output_redacted, iterations}.
    """
    history = history or []
    result = {
        "response": "",
        "mode": config.AGENT_MODE,
        "tools_used": [],
        "blocked_by_input_guard": False,
        "output_redacted": False,
        "iterations": 0,
    }

    # --- Input Guard (protected) ---
    if config.AGENT_MODE == "protected":
        allowed, reason = guards.input_guard(user_input)
        if not allowed:
            result["response"] = policy.REFUSAL
            result["blocked_by_input_guard"] = True
            result["guard_reason"] = reason
            logger.info("Input guard blocked request: %s", reason)
            return result

    tool_schemas, dispatch = _select_tools()
    sys_prompt = _system_prompt()

    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})

    for i in range(config.MAX_TOOL_ITERATIONS):
        result["iterations"] = i + 1
        try:
            resp = llm.chat_completion(messages, tools=tool_schemas)
        except Exception as e:  # noqa: BLE001
            logger.error("LLM call failed: %s", e)
            result["response"] = (
                f"[LLM unavailable] The agent could not reach the model ({e}). "
                "Ensure Ollama is running and the model is pulled."
            )
            return result

        choice = resp.choices[0]
        msg = choice.message

        # Если нет tool_calls — финальный ответ
        if not msg.tool_calls:
            final = msg.content or ""
            break

        # Выполняем tool calls
        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                fn_args = {}
            logger.info("Tool call: %s args=%s", fn_name, fn_args)
            tool_result = dispatch(fn_name, fn_args)
            result["tools_used"].append({"name": fn_name, "args": fn_args})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": fn_name,
                "content": str(tool_result)[:4000],
            })
    else:
        final = "[Agent reached max tool iterations without a final answer.]"

    # --- Output Guard (protected) ---
    if config.AGENT_MODE == "protected":
        safe, leaked = guards.output_guard(final)
        if leaked:
            result["output_redacted"] = True
            result["output_leaked"] = leaked
            final = safe

    result["response"] = final
    return result
