from collections.abc import Callable
from typing import Any

from gis_agent.persistence.checkpoints import (
    MemoryCheckpointer,
    SqliteCheckpointer,
    StateSnapshot,
    coerce_checkpointer,
)


class AgentLoopRunner:
    """无第三方编排库依赖的确定性 model -> tools -> finish 状态机。"""

    def __init__(
        self,
        model_step: Callable[[dict[str, Any]], dict[str, Any]],
        tools_step: Callable[[dict[str, Any]], dict[str, Any]],
        finish_step: Callable[[dict[str, Any]], dict[str, Any]],
        checkpointer: Any = None,
    ) -> None:
        self._model = model_step
        self._tools = tools_step
        self._finish = finish_step
        self.backend: MemoryCheckpointer | SqliteCheckpointer = coerce_checkpointer(checkpointer)

    @staticmethod
    def _thread_id(options: dict[str, Any]) -> str:
        return str(options["configurable"]["thread_id"])

    def get_state(self, options: dict[str, Any]) -> StateSnapshot:
        return self.backend.get(self._thread_id(options))

    def update_state(
        self,
        options: dict[str, Any],
        values: dict[str, Any],
        as_node: str = "tools",
        pending_call: dict[str, Any] | None = None,
    ) -> StateSnapshot:
        thread_id = self._thread_id(options)
        current = dict(self.backend.get(thread_id).values)
        current.update(values)
        if as_node == "finish" or current.get("outcome") is not None:
            next_nodes: tuple[str, ...] = ()
        elif as_node == "model":
            next_nodes = ("tools",)
        else:
            next_nodes = ("model",)
        return self.backend.put(thread_id, current, next_nodes, pending_call=pending_call)

    def invoke(self, initial_state: dict[str, Any] | None, options: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        thread_id = self._thread_id(options)
        if initial_state is not None:
            state = dict(initial_state)
            next_step = "model"
        else:
            snap = self.backend.get(thread_id)
            if not snap.next:
                return snap.values
            state = dict(snap.values)
            next_step = snap.next[0]

        if next_step == "model":
            model_updates = self._model(state)
            state.update(model_updates)
            if state.get("outcome") is not None:
                finish_updates = self._finish(state)
                state.update(finish_updates)
                self.backend.put(thread_id, state, (), pending_call=None)
                return state
            # 模型响应落盘后先记录 ("tools",) 边界检查点，确保工具中途崩溃可被准确识别
            self.backend.put(thread_id, state, ("tools",), pending_call=None)

        state = dict(self._tools(state))
        if state.get("outcome") is not None:
            finish_updates = self._finish(state)
            state.update(finish_updates)
            self.backend.put(thread_id, state, (), pending_call=None)
            return state

        self.backend.put(thread_id, state, ("model",), pending_call=None)
        return state
