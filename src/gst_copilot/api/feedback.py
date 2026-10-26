"""POST /feedback: 👍 or 👎 (and an optional note) on an answer from /ask."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.db.session import get_session
from gst_copilot.observe.store import set_feedback

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    ask_id: int
    rating: Literal[1, -1]  # 1 = helpful, -1 = not helpful
    note: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    ok: bool = True


@router.post("/feedback", response_model=FeedbackResponse)
async def feedback_endpoint(
    body: FeedbackRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> FeedbackResponse:
    if not await set_feedback(session, body.ask_id, body.rating, body.note):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No answer with ask_id {body.ask_id}.")
    return FeedbackResponse()
