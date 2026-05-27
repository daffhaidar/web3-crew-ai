"""Tests for per-command skill routing in SkillManager.

Covers the routing rules from AGENTS.md:
  - Identity files (HEARTBEAT / IDENTITY / SOUL) always load.
  - ``m*`` skill files only load when their prefix matches the requested
    command in :attr:`SkillManager.COMMAND_SKILL_MAP`.
  - When ``command`` is None the legacy "load everything" behavior is
    preserved so existing call sites stay backward-compatible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from web3_crew.memory.skill_ingestor import SkillManager

# --- fixtures ---------------------------------------------------------------


@pytest.fixture()
def populated_skills_dir(tmp_path: Path) -> Path:
    """Create a minimal skills directory mirroring the production layout."""
    skills = tmp_path / "skills"
    skills.mkdir()

    # Identity files (always-on)
    (skills / "HEARTBEAT.md").write_text("# heartbeat\nkeep alive\n", encoding="utf-8")
    (skills / "IDENTITY.md").write_text("# identity\nname: bot\n", encoding="utf-8")
    (skills / "SOUL.md").write_text("# soul\nflexibility doctrine\n", encoding="utf-8")

    # Skill modules (load on command match)
    (skills / "m4_telegram_bots.md").write_text("# m4\ntelegram patterns\n", encoding="utf-8")
    (skills / "m10_web3_ops.md").write_text("# m10\nrpc fallback\n", encoding="utf-8")
    (skills / "m11_security_audit.md").write_text("# m11\nred flags\n", encoding="utf-8")
    (skills / "m13_nft_minter.md").write_text("# m13\nopensea minter\n", encoding="utf-8")

    return skills


# --- identity always-on -----------------------------------------------------


def test_identity_files_always_load_for_known_command(populated_skills_dir: Path) -> None:
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context(command="mint")

    assert "HEARTBEAT.md" in ctx
    assert "IDENTITY.md" in ctx
    assert "SOUL.md" in ctx


def test_identity_files_load_when_command_is_none(populated_skills_dir: Path) -> None:
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context()

    assert "HEARTBEAT.md" in ctx
    assert "IDENTITY.md" in ctx
    assert "SOUL.md" in ctx


# --- per-command filtering --------------------------------------------------


def test_mint_command_loads_m10_and_m13_only(populated_skills_dir: Path) -> None:
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context(command="mint")

    assert "m10_web3_ops.md" in ctx
    assert "m13_nft_minter.md" in ctx
    assert "m11_security_audit.md" not in ctx
    assert "m4_telegram_bots.md" not in ctx


def test_check_command_loads_only_m11(populated_skills_dir: Path) -> None:
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context(command="check")

    assert "m11_security_audit.md" in ctx
    assert "m10_web3_ops.md" not in ctx
    assert "m13_nft_minter.md" not in ctx
    assert "m4_telegram_bots.md" not in ctx


def test_chat_command_loads_only_m4(populated_skills_dir: Path) -> None:
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context(command="chat")

    assert "m4_telegram_bots.md" in ctx
    assert "m10_web3_ops.md" not in ctx
    assert "m11_security_audit.md" not in ctx
    assert "m13_nft_minter.md" not in ctx


# --- legacy / fallback ------------------------------------------------------


def test_unknown_command_falls_back_to_loading_everything(populated_skills_dir: Path) -> None:
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context(command="nope_unknown_command")

    # Unknown command should NOT silently filter to empty \u2014 load all so
    # the bot keeps responding even with a typo in COMMAND_SKILL_MAP.
    assert "m10_web3_ops.md" in ctx
    assert "m11_security_audit.md" in ctx


def test_no_command_loads_every_skill_file(populated_skills_dir: Path) -> None:
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context()

    for name in [
        "HEARTBEAT.md", "IDENTITY.md", "SOUL.md",
        "m4_telegram_bots.md", "m10_web3_ops.md",
        "m11_security_audit.md", "m13_nft_minter.md",
    ]:
        assert name in ctx, f"{name} should load when no command is given"


# --- prefix matching edge cases ---------------------------------------------


def test_prefix_match_does_not_leak_across_similar_names(tmp_path: Path) -> None:
    """``m1`` must NOT match ``m10`` / ``m11`` / ``m13`` etc."""
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "HEARTBEAT.md").write_text("x", encoding="utf-8")
    (skills / "m1_monetize.md").write_text("monetize\n", encoding="utf-8")
    (skills / "m10_web3_ops.md").write_text("web3\n", encoding="utf-8")
    (skills / "m11_security.md").write_text("audit\n", encoding="utf-8")

    mgr = SkillManager(skills_dir=skills)
    # Patch the routing table to point a fake command at m1 only.
    mgr.COMMAND_SKILL_MAP = {"fake": ("m1",)}  # type: ignore[misc]

    ctx = mgr.get_skill_context(command="fake")

    assert "m1_monetize.md" in ctx
    assert "m10_web3_ops.md" not in ctx
    assert "m11_security.md" not in ctx


def test_empty_skills_dir_returns_empty_string(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()

    mgr = SkillManager(skills_dir=skills)

    assert mgr.get_skill_context(command="mint") == ""
    assert mgr.get_skill_context() == ""


# --- budget headroom --------------------------------------------------------


def test_mint_context_fits_under_max_chars(populated_skills_dir: Path) -> None:
    """Make sure per-command filtering actually keeps us inside the budget.

    With identity + m10 + m13 the unfiltered load blows through the cap.
    Per-command filter must still respect ``MAX_CONTEXT_CHARS``, so the
    result is truncated -- not exploded.
    """
    mgr = SkillManager(skills_dir=populated_skills_dir)

    ctx = mgr.get_skill_context(command="mint")

    # Hard ceiling; allow tiny overhead for headers / truncation notice.
    assert len(ctx) <= mgr.MAX_CONTEXT_CHARS + 200


# --- partial-load behavior --------------------------------------------------
# These guard the regression that motivated this PR: under the previous
# "stop entirely if the next file does not fit" logic, a single big skill
# file would silently drop ALL m-skills, making the per-command router
# pointless in production.


def test_oversized_skill_is_partially_loaded_not_dropped(tmp_path: Path) -> None:
    """A file larger than the remaining budget must still load partially."""
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "HEARTBEAT.md").write_text("HEARTBEAT-MARK\n", encoding="utf-8")
    (skills / "m99_huge.md").write_text("HUGE-MARK\n" + ("x" * 50_000), encoding="utf-8")

    mgr = SkillManager(skills_dir=skills)
    mgr.COMMAND_SKILL_MAP = {"huge": ("m99",)}  # type: ignore[misc]

    ctx = mgr.get_skill_context(command="huge")

    # Header for the oversized file must be present (no silent drop).
    assert "=== m99_huge.md ===" in ctx
    # And the partial-truncation notice should fire.
    assert "TRUNCATED" in ctx
    # Final result respects the cap.
    assert len(ctx) <= mgr.MAX_CONTEXT_CHARS + 200


def test_partial_load_preserves_earlier_files_in_full(tmp_path: Path) -> None:
    """When a later file is partial-cut, earlier files stay intact."""
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "HEARTBEAT.md").write_text("HEARTBEAT-FULL-MARK\n", encoding="utf-8")
    (skills / "IDENTITY.md").write_text("IDENTITY-FULL-MARK\n", encoding="utf-8")
    (skills / "m77_big.md").write_text("BIG-START-MARK\n" + ("y" * 30_000), encoding="utf-8")

    mgr = SkillManager(skills_dir=skills)
    mgr.COMMAND_SKILL_MAP = {"big": ("m77",)}  # type: ignore[misc]

    ctx = mgr.get_skill_context(command="big")

    # Earlier (in-budget) files load fully.
    assert "HEARTBEAT-FULL-MARK" in ctx
    assert "IDENTITY-FULL-MARK" in ctx
    # The big file gets its header and partial body.
    assert "=== m77_big.md ===" in ctx
    assert "BIG-START-MARK" in ctx
    # But not the full body.
    assert ctx.count("y") < 30_000


# --- HERMES.md is always-on -------------------------------------------------


def test_hermes_loads_as_identity_for_every_known_command(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "HERMES.md").write_text("HERMES-MARK\n", encoding="utf-8")
    (skills / "SOUL.md").write_text("SOUL-MARK\n", encoding="utf-8")
    (skills / "m10_web3_ops.md").write_text("m10\n", encoding="utf-8")
    (skills / "m11_security_audit.md").write_text("m11\n", encoding="utf-8")
    (skills / "m4_telegram_bots.md").write_text("m4\n", encoding="utf-8")

    mgr = SkillManager(skills_dir=skills)

    for cmd in ("mint", "check", "chat"):
        ctx = mgr.get_skill_context(command=cmd)
        assert "HERMES-MARK" in ctx, f"HERMES.md missing for /{cmd}"
        assert "SOUL-MARK" in ctx, f"SOUL.md missing for /{cmd}"


def test_production_check_pipeline_loads_m11_fully(tmp_path: Path) -> None:
    """Regression guard: /check must include the full audit playbook.

    Pre-PR this test would have failed because the 12K cap caused m11 to be
    silently dropped after identity loaded. Verifies the combination of
    bigger cap + partial-load semantics actually delivers the m-skill body
    to the LLM.
    """
    skills = tmp_path / "skills"
    skills.mkdir()
    # Use realistic sizes from production.
    (skills / "HEARTBEAT.md").write_text("h" * 1500, encoding="utf-8")
    (skills / "HERMES.md").write_text("hermes-mark\n" + ("e" * 2900), encoding="utf-8")
    (skills / "IDENTITY.md").write_text("i" * 1900, encoding="utf-8")
    (skills / "SOUL.md").write_text("s" * 3100, encoding="utf-8")
    (skills / "m11_security_audit.md").write_text(
        "M11-START\n" + ("a" * 6000) + "\nM11-END", encoding="utf-8"
    )

    mgr = SkillManager(skills_dir=skills)

    ctx = mgr.get_skill_context(command="check")

    assert "hermes-mark" in ctx
    assert "M11-START" in ctx
    assert "M11-END" in ctx  # full m11 body, not partial-cut
