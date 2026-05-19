"""Tests for the SkillRouterTool — keyword routing + skill body loading.

These tests pin the routing contract that the ChatAgent depends on:

1. English and Indonesian keywords route to the expected skill.
2. Multi-word and high-signal keywords carry extra weight.
3. ``no match`` cases return an empty :class:`SkillMatch` so the agent can
   gracefully fall back to core knowledge.
4. Frontmatter is stripped from loaded SKILL.md bodies.
5. The CrewAI ``_run`` surface returns deterministic text including the
   PRIMARY / SUPPORTING headers the agent prompt expects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from web3_crew.tools.skill_router import (
    SKILL_REGISTRY,
    SkillMatch,
    SkillRouterTool,
    _strip_frontmatter,
    default_skill_dir,
    load_skill_body,
    match_skills,
)

# ---------------------------------------------------------------------------
# match_skills — routing logic
# ---------------------------------------------------------------------------


class TestMatchSkills:
    @pytest.mark.parametrize(
        ("query", "expected_primary"),
        [
            ("cara setup VPS Ubuntu untuk Node.js", "m2-server-deploy"),
            ("how to deploy a docker container on linux", "m2-server-deploy"),
            ("3 cara monetize bot Telegram", "m1-monetize"),
            ("bikin landing page react", "m9-frontend-web"),
            ("debug error TypeError list out of range", "x3-debug-error"),
            ("api integration with stripe", "m6-api-integration"),
            ("buat caption viral untuk tiktok", "m3-content-viral"),
            ("export data ke excel xlsx", "m8-file-export"),
            ("analisis data dari csv", "m5-data-analytics"),
            ("prompt design untuk LLM Claude", "m7-ai-agents"),
            ("audit skill saya dong", "x1-audit-system"),
        ],
    )
    def test_routes_indonesian_and_english_to_expected_primary(self, query, expected_primary):
        match = match_skills(query)
        assert match.primary == expected_primary, (
            f"Query {query!r} routed to {match.primary!r}, expected {expected_primary!r}. "
            f"Scores: {dict(sorted(match.scores.items(), key=lambda kv: -kv[1])[:3])}"
        )

    def test_routes_web3_specific_queries_to_repo_skills(self):
        # /mint + reverted should pull both telegram-bot-commands AND
        # safe-transaction-defensive-stack so the agent can answer about the
        # Web3 bot itself.
        match = match_skills("kenapa /mint tadi bilang reverted")
        assert match.primary in {
            "telegram-bot-commands",
            "safe-transaction-defensive-stack",
        }
        # The other one must appear as supporting context.
        related = {match.primary, *match.supporting}
        assert "safe-transaction-defensive-stack" in related
        assert "telegram-bot-commands" in related

    def test_empty_input_returns_no_match(self):
        match = match_skills("")
        assert match.matched is False
        assert match.primary is None
        assert match.supporting == []

    @pytest.mark.parametrize("query", ["apa kabar bro", "haha lol", "hello"])
    def test_unrelated_input_returns_no_match(self, query):
        match = match_skills(query)
        assert match.matched is False
        assert match.primary is None

    def test_supporting_is_capped(self):
        # A query that mentions keywords from many skills must not blow out
        # the context budget — we cap supporting matches.
        query = (
            "deploy bot ke vps linux, jualan akses api, viral tiktok, "
            "landing page react, audit skill saya, debug error"
        )
        match = match_skills(query, max_supporting=2)
        assert match.matched is True
        # 1 primary + at most 2 supporting = 3 total returned skills.
        assert len(match.supporting) <= 2

    def test_high_signal_keyword_wins_ties(self):
        # "deploy" is a HIGH_SIGNAL keyword for m2 and should beat a generic
        # single-word match from a different skill.
        match = match_skills("data deploy")
        assert match.primary == "m2-server-deploy"

    def test_keyword_match_is_word_bounded(self):
        # "bottom" should NOT match "bot" via substring leakage.
        match = match_skills("hit the bottom of the page")
        # Either no match or at least not m4 from a "bot" false positive.
        if match.matched:
            assert match.primary != "m4-bot-automation"


# ---------------------------------------------------------------------------
# Frontmatter & skill body loading
# ---------------------------------------------------------------------------


class TestFrontmatterAndLoader:
    def test_strip_frontmatter_removes_leading_yaml_block(self):
        raw = "---\nname: foo\ndescription: bar\n---\n\n# Body\nText"
        out = _strip_frontmatter(raw)
        assert out.startswith("# Body")
        assert "name: foo" not in out

    def test_strip_frontmatter_leaves_body_alone_when_absent(self):
        raw = "# No frontmatter\n\nBody only."
        assert _strip_frontmatter(raw) == raw

    def test_strip_frontmatter_only_removes_first_block(self):
        # A `---` inside the body must NOT be treated as a frontmatter close.
        raw = "---\nname: x\n---\n\nBody\n\n---\n\nMore body."
        out = _strip_frontmatter(raw)
        assert out.startswith("Body")
        assert "More body." in out

    def test_load_skill_body_strips_frontmatter(self, tmp_path: Path):
        skill_dir = tmp_path / "skills"
        (skill_dir / "fake-skill").mkdir(parents=True)
        (skill_dir / "fake-skill" / "SKILL.md").write_text(
            "---\nname: fake-skill\ndescription: just for testing\n---\n\n# Fake\n\nBody.",
            encoding="utf-8",
        )
        body = load_skill_body("fake-skill", skill_dir)
        assert body.startswith("# Fake")
        assert "description: just for testing" not in body

    def test_load_skill_body_raises_when_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_skill_body("does-not-exist", tmp_path)

    def test_default_skill_dir_resolves_repo_location(self):
        sd = default_skill_dir()
        assert sd.is_dir()
        assert sd.name == "skills"
        # Sanity: at least one known imported skill exists at this location.
        assert (sd / "m2-server-deploy" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# CrewAI tool surface — _run()
# ---------------------------------------------------------------------------


class TestSkillRouterTool:
    def test_tool_run_returns_primary_and_supporting_sections(self):
        tool = SkillRouterTool()
        out = tool._run("cara setup VPS ubuntu node.js")
        assert "=== m2-server-deploy [PRIMARY" in out
        # Multi-skill section block must include role + score for each.
        assert "score=" in out

    def test_tool_run_returns_no_match_notice(self):
        tool = SkillRouterTool()
        out = tool._run("apa kabar lol")
        assert "No skill matched" in out
        # No skill frontmatter should leak into a no-match response.
        assert "===" not in out

    def test_tool_run_handles_missing_skill_dir(self, tmp_path: Path):
        tool = SkillRouterTool(skill_dir=tmp_path)
        # Even though match returns a primary, the loader can't read it.
        out = tool._run("deploy vps linux")
        assert "failed to read content" in out or "No skill matched" in out


# ---------------------------------------------------------------------------
# Registry hygiene — every registered skill has a matching file on disk
# ---------------------------------------------------------------------------


class TestRegistryHygiene:
    def test_every_registered_skill_has_a_file_on_disk(self):
        skill_dir = default_skill_dir()
        missing = [
            sid for sid in SKILL_REGISTRY if not (skill_dir / sid / "SKILL.md").is_file()
        ]
        assert not missing, f"Registry references missing files: {missing}"

    def test_skill_registry_has_no_duplicate_keywords_within_a_skill(self):
        for sid, kws in SKILL_REGISTRY.items():
            assert len(kws) == len(set(kws)), f"Duplicate keyword in {sid}"


# ---------------------------------------------------------------------------
# SkillMatch dataclass
# ---------------------------------------------------------------------------


class TestSkillMatchDataclass:
    def test_matched_property_reflects_primary(self):
        assert SkillMatch().matched is False
        assert SkillMatch(primary="m1-monetize").matched is True
