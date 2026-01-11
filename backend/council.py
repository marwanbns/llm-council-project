"""
Pipeline pour les étapes.
"""
from __future__ import annotations
import time
import uuid
from datetime import datetime
from typing import Dict, Optional
from loguru import logger
from .llm_service import get_llm_service
from .models import CouncilSession, CouncilStage, ReviewRoundResponse


class CouncilOrchestrator:
    def __init__(self):
        self._sessions: Dict[str, CouncilSession] = {}
        self._inflight: int = 0

    def create_session(self, user_query: str):
        sid = str(uuid.uuid4())[:8]
        session = CouncilSession(session_id=sid, query=user_query, stage=CouncilStage.PENDING)
        self._sessions[sid] = session
        return session

    def get_session(self, session_id: str):
        return self._sessions.get(session_id)

    def get_all_sessions(self):
        return list(self._sessions.values())

    @property
    def active_sessions(self):
        return self._inflight

    @property
    def total_sessions(self):
        return len(self._sessions)

    # On va run chaque étape
    async def _stage_first_opinions(self, session: CouncilSession) -> None:
        logger.info(f"Session {session.session_id}: Stage 1 start (first opinions)")
        session.stage = CouncilStage.FIRST_OPINIONS

        svc = get_llm_service()
        answers = await svc.get_all_first_opinions(session.query)
        session.first_opinions = answers

        logger.info(f"Session {session.session_id}: Stage 1 done ({len(answers)} opinion(s))")

    async def _stage_reviews(self, session: CouncilSession) -> None:
        if not session.first_opinions:
            raise ValueError("Stage 2 requires stage 1 outputs (first_opinions).")

        logger.info(f"Session {session.session_id}: Stage 2 start (review & ranking)")
        session.stage = CouncilStage.REVIEW_RANKING

        svc = get_llm_service()
        reviews, averages = await svc.get_all_reviews(session.query, session.first_opinions)
        session.review_results = ReviewRoundResponse(reviews=reviews, rankings=averages)

        logger.info(f"Session {session.session_id}: Stage 2 done ({len(reviews)} review(s))")

    async def _stage_chairman(self, session: CouncilSession) -> None:
        if not session.first_opinions:
            raise ValueError("Stage 3 requires stage 1 outputs (first_opinions).")

        logger.info(f"Session {session.session_id}: Stage 3 start (chairman synthesis)")
        session.stage = CouncilStage.CHAIRMAN_SYNTHESIS

        svc = get_llm_service()
        reviews = session.review_results.reviews if session.review_results else []
        rankings = session.review_results.rankings if session.review_results else {}

        summary = await svc.get_chairman_synthesis(session.query, session.first_opinions, reviews, rankings)
        session.chairman_synthesis = summary

        session.stage = CouncilStage.COMPLETED
        session.completed_at = datetime.utcnow()

        logger.info(f"Session {session.session_id}: Stage 3 done (completed)")

    # API
    async def run_full_council(self, query: str) -> CouncilSession:
        t0 = time.perf_counter()
        self._inflight += 1

        session = self.create_session(query)
        logger.info(f"Session {session.session_id}: pipeline start")

        try:
            await self._stage_first_opinions(session)
            await self._stage_reviews(session)
            await self._stage_chairman(session)

            session.total_latency_ms = (time.perf_counter() - t0) * 1000
            logger.info(f"Session {session.session_id}: pipeline done in {session.total_latency_ms:.0f}ms")
            return session

        except Exception as e:
            logger.error(f"Session {session.session_id}: pipeline error: {e}")
            session.stage = CouncilStage.ERROR
            session.error_message = str(e)
            raise

        finally:
            self._inflight -= 1

    async def run_council_streaming(self, query: str):
        t0 = time.perf_counter()
        self._inflight += 1

        session = self.create_session(query)

        try:
            yield session  # pending snapshot

            await self._stage_first_opinions(session)
            yield session

            await self._stage_reviews(session)
            yield session

            await self._stage_chairman(session)
            session.total_latency_ms = (time.perf_counter() - t0) * 1000
            yield session

        except Exception as e:
            logger.error(f"Session {session.session_id}: streaming error: {e}")
            session.stage = CouncilStage.ERROR
            session.error_message = str(e)
            yield session

        finally:
            self._inflight -= 1


_ORCHESTRATOR: Optional[CouncilOrchestrator] = None


def get_orchestrator() -> CouncilOrchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = CouncilOrchestrator()
    return _ORCHESTRATOR