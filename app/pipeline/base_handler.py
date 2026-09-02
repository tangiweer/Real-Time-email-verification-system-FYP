from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from app.models import PipelineContext


class BaseEmailHandler(ABC):


    def __init__(self) -> None:
        self._next_handler: Optional["BaseEmailHandler"] = None

    def set_next(self, handler: BaseEmailHandler) -> BaseEmailHandler:

        self._next_handler = handler
        return handler

    async def handle(self, context: PipelineContext) -> PipelineContext:

        if self._next_handler and not context.stop_processing:
            return await self._next_handler.handle(context)
        return context

    def warmup(self) -> None:

        if self._next_handler:
            self._next_handler.warmup()

    @property
    def layer_name(self) -> str:

        return self.__class__.__name__.replace("Handler", "").lower()
