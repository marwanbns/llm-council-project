"""
Toutes les méthodes avec les prompts systèmes pour les LLM.
"""
from __future__ import annotations
import asyncio
import re
import time
from typing import Dict, List, Optional, Tuple
import httpx
from loguru import logger
from .config import LLMNode, get_config
from .models import (
    ChairmanSynthesis,
    FirstOpinionResponse,
    LLMNodeInfo,
    LLMStatus,
    ReviewScore,
)


class LLMService:
    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self._http = httpx.AsyncClient(timeout=timeout)
        self._status_cache: Dict[str, LLMStatus] = {}
        self._latency_cache: Dict[str, float] = {}

    async def close(self):
        await self._http.aclose()

    # Pour verifier que les requêtes fonctionne
    async def check_node_health(self, node: LLMNode):
        """
        On retourne le status et la latence (en ms)
        """
        try:
            t0 = time.perf_counter()
            r = await self._http.get(node.health_url, timeout=10)
            dt = (time.perf_counter() - t0) * 1000

            if r.status_code != 200:
                self._status_cache[node.name] = LLMStatus.ERROR
                return LLMStatus.ERROR, None

            payload = r.json()
            installed = [m.get("name", "").split(":")[0] for m in payload.get("models", [])]
            requested = node.model.split(":")[0]

            if installed and requested not in installed:
                logger.warning(f"{node.name}: model {node.model!r} not listed in /api/tags (found={installed}).")

            self._status_cache[node.name] = LLMStatus.ONLINE
            self._latency_cache[node.name] = dt
            return LLMStatus.ONLINE, dt

        except httpx.TimeoutException:
            logger.warning(f"{node.name}: health probe timed out.")
            self._status_cache[node.name] = LLMStatus.OFFLINE
            return LLMStatus.OFFLINE, None

        except Exception as e:
            logger.error(f"{node.name}: health probe failed: {e}")
            self._status_cache[node.name] = LLMStatus.OFFLINE
            return LLMStatus.OFFLINE, None

    async def check_all_nodes_health(self):
        cfg = get_config()
        nodes: List[LLMNode] = cfg.council_members + ([cfg.chairman] if cfg.chairman else [])
        results = await asyncio.gather(*(self.check_node_health(n) for n in nodes))
        out: List[LLMNodeInfo] = []
        for node, (status, latency) in zip(nodes, results):
            out.append(
                LLMNodeInfo(
                    name=node.name,
                    host=node.host,
                    port=node.port,
                    model=node.model,
                    is_chairman=node.is_chairman,
                    status=status,
                    latency_ms=latency,
                )
            )
        return out

    def get_node_status(self, node_name: str):
        return self._status_cache.get(node_name, LLMStatus.OFFLINE)

    def get_node_latency(self, node_name: str):
        return self._latency_cache.get(node_name)

    async def generate_response(
        self,
        node: LLMNode,
        prompt: str,
        system_prompt: Optional[str] = None,
    ):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body = {"model": node.model, "messages": messages, "stream": False}

        try:
            self._status_cache[node.name] = LLMStatus.BUSY

            t0 = time.perf_counter()
            r = await self._http.post(node.chat_url, json=body, timeout=self.timeout)
            dt = (time.perf_counter() - t0) * 1000

            self._status_cache[node.name] = LLMStatus.ONLINE
            self._latency_cache[node.name] = dt

            if r.status_code != 200:
                logger.error(f"{node.name}: /api/chat failed ({r.status_code}) {r.text[:200]}")
                raise RuntimeError(f"LLM returned status {r.status_code}")

            payload = r.json()
            text = payload.get("message", {}).get("content", "")

            # token-ish stats when available
            tokens = None
            if "eval_count" in payload:
                tokens = payload.get("eval_count")
            elif "prompt_eval_count" in payload and "eval_count" in payload:
                tokens = payload.get("prompt_eval_count", 0) + payload.get("eval_count", 0)

            return text, dt, tokens

        except httpx.TimeoutException:
            self._status_cache[node.name] = LLMStatus.ERROR
            logger.error(f"{node.name}: generation timeout.")
            raise

        except Exception as e:
            self._status_cache[node.name] = LLMStatus.ERROR
            logger.error(f"{node.name}: generation error: {e}")
            raise

    # Prompt système pour la 1ère étape
    async def get_first_opinion(self, node: LLMNode, query: str):
        sys_msg = (
            "You are a council member. Provide a clear, accurate answer to the user's question. "
            "Be helpful and structured. Your answer will be peer-reviewed."
        )

        text, ms, tok = await self.generate_response(node=node, prompt=query, system_prompt=sys_msg)
        return FirstOpinionResponse(
            llm_name=node.name,
            model=node.model,
            response=text,
            latency_ms=ms,
            token_count=tok,
        )

    async def get_all_first_opinions(self, query: str):
        cfg = get_config()
        jobs = [self.get_first_opinion(n, query) for n in cfg.council_members]
        results = await asyncio.gather(*jobs, return_exceptions=True)

        opinions: List[FirstOpinionResponse] = []
        for item in results:
            if isinstance(item, Exception):
                logger.error(f"Stage 1 error: {item}")
                continue
            opinions.append(item)
        return opinions

    # Prompt système pour la 2ème étape
    async def get_review(
        self,
        reviewer_node: LLMNode,
        query: str,
        responses: List[Tuple[str, str, str]],  # (anon_name, response_text, original_llm_name)
        exclude_name: str,
    ):
        pool = [(anon, txt, orig) for (anon, txt, orig) in responses if orig != exclude_name]
        if not pool:
            return []

        block = "\n\n".join([f"=== {anon} ===\n{txt}" for (anon, txt, _) in pool])

        sys_msg = (
            "You are a strict reviewer. Score each response on Accuracy (1-10) and Insight (1-10). "
            "Give a brief justification. Avoid style bias."
        )

        prompt = (
            f"Original Query: {query}\n\n"
            "Below are anonymized answers from other models:\n\n"
            f"{block}\n\n"
            "For each response, use the exact template:\n"
            "[Response Name]\n"
            "Accuracy Score: X/10\n"
            "Insight Score: X/10\n"
            "Reasoning: ...\n"
        )

        try:
            raw, _, _ = await self.generate_response(node=reviewer_node, prompt=prompt, system_prompt=sys_msg)
            return self._parse_review_response(reviewer_node.name, raw, pool)
        except Exception as e:
            logger.error(f"Stage 2: reviewer {reviewer_node.name} failed: {e}")
            return []

    def _parse_review_response(
        self,
        reviewer_name: str,
        review_text: str,
        pool: List[Tuple[str, str, str]],
    ):
        out: List[ReviewScore] = []

        for anon_name, _, original_name in pool:
            try:
                # scores
                m = re.search(
                    rf"{re.escape(anon_name)}.*?Accuracy.*?(\d+).*?Insight.*?(\d+)",
                    review_text,
                    re.IGNORECASE | re.DOTALL,
                )
                if m:
                    acc = min(10, max(1, int(m.group(1))))
                    ins = min(10, max(1, int(m.group(2))))
                else:
                    acc, ins = 7, 7

                # reasoning (best-effort)
                rm = re.search(
                    rf"{re.escape(anon_name)}.*?Reasoning[:\s]+([^\[]+)",
                    review_text,
                    re.IGNORECASE | re.DOTALL,
                )
                reasoning = rm.group(1).strip()[:500] if rm else "No detailed reasoning extracted."

                out.append(
                    ReviewScore(
                        reviewer_name=reviewer_name,
                        reviewed_name=anon_name,
                        original_name=original_name,
                        score=(acc + ins) // 2,
                        reasoning=reasoning,
                        accuracy_score=acc,
                        insight_score=ins,
                    )
                )
            except Exception as e:
                logger.warning(f"Review parse fallback for {anon_name}: {e}")
                out.append(
                    ReviewScore(
                        reviewer_name=reviewer_name,
                        reviewed_name=anon_name,
                        original_name=original_name,
                        score=7,
                        reasoning="Parsing failed; default scores applied.",
                        accuracy_score=7,
                        insight_score=7,
                    )
                )

        return out

    async def get_all_reviews(
        self,
        query: str,
        first_opinions: List[FirstOpinionResponse],
    ):
        cfg = get_config()

        # Pour anonymiser les réponses
        anon_bundle: List[Tuple[str, str, str]] = []
        for i, op in enumerate(first_opinions):
            label = f"Response {chr(65 + i)}"
            anon_bundle.append((label, op.response, op.llm_name))

        jobs = [
            self.get_review(
                reviewer_node=node,
                query=query,
                responses=anon_bundle,
                exclude_name=node.name,
            )
            for node in cfg.council_members
        ]

        results = await asyncio.gather(*jobs, return_exceptions=True)

        all_scores: List[ReviewScore] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Stage 2 error: {r}")
                continue
            all_scores.extend(r)

        # aggregate by original_name
        buckets: Dict[str, List[float]] = {}
        for sc in all_scores:
            buckets.setdefault(sc.original_name, []).append(sc.score)

        averages = {name: (sum(vals) / len(vals) if vals else 0.0) for name, vals in buckets.items()}
        return all_scores, averages

    # Prompt sytème pour le Chairman et pour la dernière étape
    async def get_chairman_synthesis(
        self,
        query: str,
        first_opinions: List[FirstOpinionResponse],
        reviews: List[ReviewScore],
        rankings: Dict[str, float],
    ):
        cfg = get_config()

        answers_block = "\n\n".join(
            [f"=== {op.llm_name} (Model: {op.model}) ===\n{op.response}" for op in first_opinions]
        )

        rank_block = "\n".join(
            [f"- {name}: Average Score {score:.1f}/10" for name, score in sorted(rankings.items(), key=lambda x: -x[1])]
        )

        review_lines = [
            f"- {r.reviewer_name} rated {r.reviewed_name}: Accuracy {r.accuracy_score}/10, Insight {r.insight_score}/10"
            for r in reviews
        ]
        review_block = "\n".join(review_lines[:20])

        sys_msg = (
            "You are the Chairman. Synthesize the best elements from the council answers. "
            "Resolve conflicts, be accurate, and provide a brief reasoning summary."
        )

        prompt = (
            f"Original Query: {query}\n\n"
            "=== COUNCIL RESPONSES ===\n"
            f"{answers_block}\n\n"
            "=== PEER REVIEW RANKINGS ===\n"
            f"{rank_block}\n\n"
            "=== REVIEW HIGHLIGHTS ===\n"
            f"{review_block}\n\n"
            "Return exactly:\n"
            "FINAL ANSWER:\n"
            "[...]\n\n"
            "REASONING SUMMARY:\n"
            "[...]\n"
        )

        # Différence entre mode local et à distance
        mode = (cfg.chairman_mode or "local").lower().strip()

        if mode == "remote":
            if not cfg.chairman_remote_base_url:
                raise ValueError("chairman.mode=remote but chairman.remote.base_url is missing in config.yaml")

            url = cfg.chairman_remote_base_url.rstrip("/") + cfg.chairman_remote_endpoint

            payload = {
                "query": query,
                "system_prompt": sys_msg,
                "prompt": prompt,
                "first_opinions": [op.model_dump(mode="json") for op in first_opinions],
                "reviews": [r.model_dump(mode="json") for r in reviews],
                "rankings": rankings,
            }

            try:
                t0 = time.perf_counter()
                resp = await self._http.post(url, json=payload, timeout=cfg.chairman_remote_timeout_s)
                latency_ms = (time.perf_counter() - t0) * 1000

                if resp.status_code != 200:
                    raise RuntimeError(f"Remote chairman error {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                try:
                    return ChairmanSynthesis(**data)
                except Exception:
                    final = data.get("final_response") or data.get("final") or ""
                    reasoning = data.get("reasoning_summary") or data.get("reasoning") or ""
                    model = data.get("model") or "remote"
                    name = data.get("chairman_name") or "Remote-Chairman"
                    return ChairmanSynthesis(
                        chairman_name=name,
                        model=model,
                        final_response=final,
                        reasoning_summary=reasoning or "Synthesis returned by remote chairman.",
                        latency_ms=latency_ms,
                    )

            except Exception as e:
                logger.error(f"Remote chairman call failed: {e}")
                raise

        chair = cfg.chairman
        if chair is None:
            raise ValueError("No chairman configured")

        text, ms, _ = await self.generate_response(node=chair, prompt=prompt, system_prompt=sys_msg)

        final = text
        reason = ""
        if "FINAL ANSWER:" in text:
            parts = text.split("REASONING SUMMARY:")
            final = parts[0].replace("FINAL ANSWER:", "").strip()
            if len(parts) > 1:
                reason = parts[1].strip()

        return ChairmanSynthesis(
            chairman_name=chair.name,
            model=chair.model,
            final_response=final,
            reasoning_summary=reason or "Synthesis completed based on council inputs.",
            latency_ms=ms,
        )

_LLM_SERVICE: Optional[LLMService] = None


def get_llm_service():
    global _LLM_SERVICE
    if _LLM_SERVICE is None:
        cfg = get_config()
        _LLM_SERVICE = LLMService(timeout=cfg.llm_timeout)
    return _LLM_SERVICE


async def shutdown_llm_service():
    global _LLM_SERVICE
    if _LLM_SERVICE is not None:
        await _LLM_SERVICE.close()
        _LLM_SERVICE = None