from contextvars import ContextVar


trace_id_ctx: ContextVar[str] = ContextVar("trace_id_ctx", default=None)


def set_trace_id(trace_id: str):
    trace_id_ctx.set(trace_id)


def get_trace_id() -> str:
    return trace_id_ctx.get()
