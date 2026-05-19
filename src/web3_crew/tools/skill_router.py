"""SkillRouterTool — dynamic skill loader for the SUPERAGENT-style ChatAgent.

The ChatAgent calls this tool with the user's natural-language input. The tool
matches intent keywords (English + Indonesian) against the skill registry,
loads the matched ``SKILL.md`` file(s) from disk on demand, and returns the
body content as a single string that the agent can use as authoritative
context for its response.

Design choices
--------------
* **Dynamic loading**: skill files are read per request, not at boot. This
  means edits to ``.agents/skills/*/SKILL.md`` take effect immediately, and
  unmatched skills don't burn LLM context tokens.
* **No external matcher**: keyword matching runs locally (regex), no LLM call,
  no embedding service. Matching is deterministic and zero-cost.
* **PRIMARY + supporting**: per ``AGENTS.md`` routing rules, when multiple
  skills match, the highest-scoring one becomes PRIMARY and the rest are
  loaded as supporting context (capped at 2 to stay within token budget).
* **Frontmatter aware**: the YAML frontmatter (``---name/description---``) is
  stripped from the loaded body so the LLM sees clean markdown content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from crewai.tools import BaseTool
from pydantic import Field

# ---------------------------------------------------------------------------
# Skill registry — mirrors AGENTS.md routing table + R7 Indonesian mapping.
# ---------------------------------------------------------------------------
#
# Each entry maps a skill directory name (under .agents/skills/) to its list
# of trigger keywords. Keywords are matched as whole words (word-boundary
# regex), case-insensitively, against the normalized user input.
#
# Multi-word phrases (e.g. ``"landing page"``) match as substrings.

SkillId = str

SKILL_REGISTRY: dict[SkillId, list[str]] = {
    "m1-monetize": [
        "business", "income", "sell", "sales", "funnel", "pricing", "monetize",
        "monetization", "revenue", "cuan", "jualan", "jual", "usaha", "bisnis",
        "harga", "penjualan",
    ],
    "m2-server-deploy": [
        "server", "vps", "deploy", "deployment", "linux", "bash", "docker",
        "nginx", "ssh", "hosting", "pasang", "pasangin", "ubuntu", "debian",
        "pm2", "systemd", "certbot",
    ],
    "m3-content-viral": [
        "content", "caption", "viral", "hook", "script", "tiktok", "instagram",
        "youtube", "twitter", "konten", "naskah", "thread", "carousel",
    ],
    "m4-bot-automation": [
        "bot", "automation", "automate", "cron", "webhook", "workflow", "make",
        "n8n", "telegram bot", "otomatis", "otomasi", "jadwal", "scheduled",
    ],
    "m5-data-analytics": [
        "data", "spreadsheet", "analytics", "analysis", "report", "excel",
        "csv", "pandas", "laporan", "analisis", "dataset",
    ],
    "m6-api-integration": [
        "api", "integration", "rest", "sdk", "endpoint", "third-party",
        "integrasi", "sambungin", "konek", "midtrans", "webhook integration",
    ],
    "m7-ai-agents": [
        "ai", "prompt", "agent", "llm", "claude", "gpt", "openai", "anthropic",
        "gemini", "openrouter", "groq", "deepseek", "model", "inference",
        "agen ai", "agen",
    ],
    "m8-file-export": [
        "file", "pdf", "docx", "xlsx", "pptx", "generate", "export", "document",
        "dokumen", "spreadsheet file", "report file",
    ],
    "m9-frontend-web": [
        "website", "landing page", "frontend", "react", "html", "css", "ui",
        "tailwind", "web", "situs", "next.js", "nextjs", "vue",
    ],
    "x1-audit-system": [
        "audit", "improve system", "review agent", "upgrade system",
        "self-audit", "review skill",
    ],
    "x2-strategy-architecture": [
        "complex strategy", "multi-step", "think through", "architecture",
        "strategi", "arsitektur", "decompose", "decomposition",
    ],
    "x3-debug-error": [
        "error", "bug", "not working", "failed", "debug", "stack trace",
        "gagal", "gak jalan", "ga jalan", "rusak", "crash", "exception",
        "traceback",
    ],
    # Web3-specific (existing repo skills) — bridge so the chat agent can
    # surface them when the user asks about the bot itself.
    "setup-and-run": [
        "setup", "install", "uv sync", "first run", "install bot", "cara setup",
    ],
    "test-and-lint": [
        "test", "pytest", "ruff", "lint", "linter", "coverage",
    ],
    "architecture-overview": [
        "how does this work", "pipeline", "agent flow", "data gatherer",
        "auditor", "tx executor", "architecture overview",
    ],
    "safe-transaction-defensive-stack": [
        "reverted", "pending tx", "stuck tx", "rbf", "replace by fee",
        "budget cap", "max_tx_cost", "defensive execution",
    ],
    "telegram-bot-commands": [
        "/check", "/mint", "/start", "telegram commands", "auth wall",
        "authorized_user_id",
    ],
}

# Words that, when matched, get extra weight (so a request that mentions both
# "deploy" and "data" routes to deploy, not data).
HIGH_SIGNAL_KEYWORDS: ClassVar[set[str]] = {
    "deploy", "deployment", "vps", "server", "monetize", "cuan", "jualan",
    "viral", "tiktok", "bot", "automation", "api", "ai", "llm", "prompt",
    "pdf", "docx", "xlsx", "website", "landing page", "react", "audit",
    "debug", "error", "bug", "/check", "/mint",
}


_WORD_BOUNDARY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]*")


def _normalize(text: str) -> str:
    return text.lower().strip()


def _score_skill(user_text_lc: str, keywords: list[str]) -> int:
    """Return a match score for a skill given the user's lowercased input.

    Single-word keywords match as word-bounded tokens. Multi-word keywords
    (containing spaces) match as substrings. High-signal keywords add an extra
    bonus weight to break ties in favor of more specific matches.
    """
    score = 0
    for kw in keywords:
        kw_lc = kw.lower()
        if " " in kw_lc or "/" in kw_lc:
            if kw_lc in user_text_lc:
                score += 2 if kw_lc in HIGH_SIGNAL_KEYWORDS else 1
        else:
            pattern = re.compile(rf"\b{re.escape(kw_lc)}\b")
            if pattern.search(user_text_lc):
                score += 2 if kw_lc in HIGH_SIGNAL_KEYWORDS else 1
    return score


# ---------------------------------------------------------------------------
# Public match result type
# ---------------------------------------------------------------------------


@dataclass
class SkillMatch:
    """Result of matching a user query against the skill registry."""

    primary: SkillId | None = None
    supporting: list[SkillId] = field(default_factory=list)
    scores: dict[SkillId, int] = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        return self.primary is not None


def match_skills(
    user_input: str,
    *,
    registry: dict[SkillId, list[str]] | None = None,
    max_supporting: int = 2,
) -> SkillMatch:
    """Match the user's free-form input against the skill registry.

    Returns a :class:`SkillMatch` with the highest-scoring skill as
    :attr:`SkillMatch.primary` and up to ``max_supporting`` other matches as
    :attr:`SkillMatch.supporting`. Skills with a score of zero are not
    returned, so ``matched`` is False when nothing matches.
    """
    registry = registry or SKILL_REGISTRY
    user_lc = _normalize(user_input)
    if not user_lc:
        return SkillMatch()

    scores = {sid: _score_skill(user_lc, kws) for sid, kws in registry.items()}
    scores = {sid: s for sid, s in scores.items() if s > 0}
    if not scores:
        return SkillMatch(scores={})

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    primary = ranked[0][0]
    supporting = [sid for sid, _ in ranked[1 : 1 + max_supporting]]
    return SkillMatch(primary=primary, supporting=supporting, scores=scores)


# ---------------------------------------------------------------------------
# Skill body loader
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block, if present."""
    return _FRONTMATTER_RE.sub("", text, count=1)


def load_skill_body(skill_id: SkillId, skill_dir: Path) -> str:
    """Read ``<skill_dir>/<skill_id>/SKILL.md`` and return its body without frontmatter.

    Raises :class:`FileNotFoundError` when the skill file does not exist.
    """
    path = skill_dir / skill_id / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"Skill file not found: {path}")
    return _strip_frontmatter(path.read_text(encoding="utf-8")).strip()


# ---------------------------------------------------------------------------
# CrewAI tool surface
# ---------------------------------------------------------------------------


def default_skill_dir() -> Path:
    """Resolve the default ``.agents/skills/`` directory relative to the repo root.

    Walks up from this module's location until a directory containing
    ``.agents/skills`` is found. Falls back to ``<cwd>/.agents/skills`` if
    nothing is found upstream.
    """
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / ".agents" / "skills"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / ".agents" / "skills"


class SkillRouterTool(BaseTool):
    """CrewAI tool that routes user intent to matching SKILL.md content.

    The agent should call this tool ONCE per user turn, passing the user's
    original free-form text. The tool returns:

    * The matched skill body (PRIMARY) plus up to 2 supporting skills, with
      each section clearly headed by ``=== [skill-id] ===``.
    * Or a short "no skill matched" notice if nothing routes — telling the
      agent to fall back to core knowledge.

    The agent must NOT paste this content verbatim into its reply; it should
    synthesize an answer using the skill content as reference material.
    """

    name: str = "skill_router"
    description: str = (
        "Match the user's request to the relevant SKILL.md file(s) and return "
        "their body content. Call this tool ONCE with the user's full request "
        "text BEFORE composing your answer. Returns the matched skill markdown "
        "or a 'no match' notice. The skill content is reference material — "
        "you must rewrite it in your own words, in the user's language, with "
        "concrete examples tailored to their request."
    )
    skill_dir: Path = Field(default_factory=default_skill_dir)
    max_supporting: int = Field(default=2)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, user_request: str) -> str:  # noqa: D401 — CrewAI BaseTool API
        match = match_skills(user_request, max_supporting=self.max_supporting)
        if not match.matched:
            return (
                "[skill_router] No skill matched the user's request. Fall back "
                "to core knowledge and answer directly in SUPERAGENT style. "
                "Do not fabricate skill content."
            )

        sections: list[str] = []
        for sid in [match.primary, *match.supporting]:
            if sid is None:
                continue
            try:
                body = load_skill_body(sid, self.skill_dir)
            except FileNotFoundError:
                continue
            score = match.scores.get(sid, 0)
            role = "PRIMARY" if sid == match.primary else "SUPPORTING"
            sections.append(f"=== {sid} [{role}, score={score}] ===\n{body}")

        if not sections:
            return (
                "[skill_router] Matched skill id(s) but failed to read content. "
                "Fall back to core knowledge."
            )

        return "\n\n".join(sections)
