"""Dynamic skill ingestion module for Web3 Crew AI.

This module provides secure ZIP processing and skill context retrieval
for CrewAI agents. Skills are Markdown or text files containing domain
knowledge, rules, or instructions that are dynamically injected into
agent context.

Example:
    >>> from pathlib import Path
    >>> manager = SkillManager()
    >>> count = manager.process_zip(Path("skills.zip"))
    >>> context = manager.get_skill_context()
"""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages dynamic skill ingestion from ZIP uploads.

    This class provides secure ZIP processing and skill context retrieval
    for CrewAI agents. All methods are designed to fail gracefully and
    return safe defaults on error.

    Attributes:
        SKILLS_DIR: Path to skills directory
        ALLOWED_EXTENSIONS: Set of permitted file extensions
        FORBIDDEN_EXTENSIONS: Set of blocked file extensions
        MAX_CONTEXT_CHARS: Maximum character limit for skill context
    """

    ALLOWED_EXTENSIONS: Final[set[str]] = {".md", ".txt"}
    FORBIDDEN_EXTENSIONS: Final[set[str]] = {".py", ".sh", ".exe", ".bat", ".bin"}
    # Hard cap on injected skill context. Cerebras gpt-oss-120b has an 8192
    # token (~32K char) total budget, of which roughly half must stay free for
    # tool calls, agent reasoning, and user input. 16K characters ≈ 4K tokens
    # of skill priming — enough to fit the 3 identity files (~6.4K) plus one
    # full m-skill of ~6-10K and still leave Cerebras headroom. Files past the
    # cap are *partially* loaded (the last one is truncated mid-content) so
    # the skill router never silently drops everything when a single big file
    # would otherwise blow the budget.
    MAX_CONTEXT_CHARS: Final[int] = 16000

    # Always-on identity files. These short character / heartbeat documents
    # load on every invocation regardless of command — they are the bot's
    # voice, survival instincts, and crypto-operator code of conduct.
    # Anything else (the topic-specific skill modules) only loads when the
    # ``command`` hint matches.
    IDENTITY_FILE_PREFIXES: Final[tuple[str, ...]] = (
        "HEARTBEAT",
        "HERMES",     # Crypto operator principles (user-funds-only, etc.)
        "IDENTITY",
        "SOUL",
    )

    # Mapping from command (``mint`` / ``check`` / ``chat`` / ...) to the
    # skill prefixes that should be loaded on top of the identity files.
    # This is the lightweight version of the AGENTS.md keyword router --
    # deterministic per-command rather than per-token weighted.
    #
    # When extending: add new ``<prefix>_topic.md`` files to
    # ``memory/skills/`` then add the prefix here under whichever command
    # should pull it.
    COMMAND_SKILL_MAP: Final[dict[str, tuple[str, ...]]] = {
        "mint": ("m10", "m13"),    # Web3 ops + universal NFT minter
        "check": ("m11",),         # Security / audit playbook
        "chat": ("m4",),           # Telegram bot ops (general assistant)
    }

    def __init__(self, skills_dir: Path | None = None) -> None:
        """Initialize SkillManager with skills directory.

        Args:
            skills_dir: Path to skills directory. Defaults to
                src/web3_crew/memory/skills/ relative to project root.
        """
        if skills_dir is None:
            # Default to src/web3_crew/memory/skills/
            module_dir = Path(__file__).parent
            skills_dir = module_dir / "skills"

        self.SKILLS_DIR = skills_dir
        self._ensure_skills_directory()

    def _ensure_skills_directory(self) -> None:
        """Create skills directory if it doesn't exist."""
        try:
            self.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Skills directory ready at %s", self.SKILLS_DIR)
        except OSError as e:
            logger.error("Failed to create skills directory: %s", e)

    def process_zip(self, zip_path: Path) -> int:
        """Process uploaded ZIP file and extract skill documents.

        Args:
            zip_path: Path to uploaded ZIP file

        Returns:
            Count of successfully extracted skill files

        Raises:
            ValueError: If ZIP contains forbidden file types
            zipfile.BadZipFile: If ZIP is corrupted or invalid
            OSError: If filesystem operations fail
        """
        logger.info("Processing ZIP file: %s", zip_path)

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_file:
                # Validate contents before extraction
                self._validate_zip_contents(zip_file)

                # Extract skill files
                count = self._extract_skill_files(zip_file)

                logger.info("Successfully extracted %d skill files", count)
                return count

        except zipfile.BadZipFile as e:
            logger.error("Corrupted or invalid ZIP file: %s", e)
            raise
        except ValueError as e:
            logger.warning("ZIP validation failed: %s", e)
            raise
        except OSError as e:
            logger.error("Filesystem error during extraction: %s", e)
            raise

    def _validate_zip_contents(self, zip_file: zipfile.ZipFile) -> None:
        """Validate ZIP does not contain forbidden file types.

        Args:
            zip_file: Opened ZipFile object

        Raises:
            ValueError: If forbidden file types detected
        """
        for info in zip_file.infolist():
            # Skip directories
            if info.is_dir():
                continue

            # Extract extension (case-insensitive)
            _, ext = os.path.splitext(info.filename.lower())

            # Check blacklist
            if ext in self.FORBIDDEN_EXTENSIONS:
                raise ValueError(
                    f"Forbidden file type detected: {info.filename}"
                )

        logger.debug("ZIP validation passed")

    def _extract_skill_files(self, zip_file: zipfile.ZipFile) -> int:
        """Extract allowed files from ZIP to skills directory.

        Args:
            zip_file: Opened ZipFile object

        Returns:
            Count of extracted files
        """
        extracted_count = 0

        for info in zip_file.infolist():
            # Skip directories
            if info.is_dir():
                continue

            # Extract extension (case-insensitive)
            _, ext = os.path.splitext(info.filename.lower())

            # Only extract allowed extensions
            if ext not in self.ALLOWED_EXTENSIONS:
                continue

            # Flatten path using basename (security: prevent path traversal)
            filename = os.path.basename(info.filename)
            if not filename:
                continue

            target_path = self.SKILLS_DIR / filename

            try:
                # Extract file content
                with zip_file.open(info) as source:
                    content = source.read()

                # Write to skills directory
                target_path.write_bytes(content)
                extracted_count += 1
                logger.debug("Extracted: %s", filename)

            except Exception as e:
                logger.error("Failed to extract %s: %s", filename, e)
                continue

        return extracted_count

    def get_skill_context(self, command: str | None = None) -> str:
        """Retrieve concatenated content of relevant skill files.

        The identity files (``HEARTBEAT.md`` / ``IDENTITY.md`` / ``SOUL.md``)
        always load. When ``command`` is one of the keys in
        :attr:`COMMAND_SKILL_MAP` (``"mint"``, ``"check"``, ``"chat"``, ...)
        the matching ``m*`` skill files are also loaded on top — this is the
        lightweight skill-router implementation from AGENTS.md. When
        ``command`` is ``None`` or unrecognized, everything in the skills
        directory is loaded (backward-compatible default).

        Args:
            command: optional command name to filter on. Use ``"mint"``,
                ``"check"``, or ``"chat"`` to load only that pipeline's
                relevant skills. Pass ``None`` to load every skill file
                (legacy behavior).

        Returns:
            Formatted string with all skill content, or empty string
            if no skills exist or on error. Format::

                === filename1.md ===
                [content]

                === filename2.md ===
                [content]

                [TRUNCATED: Context exceeded MAX_CONTEXT_CHARS]
        """
        try:
            # Check if skills directory exists
            if not self.SKILLS_DIR.exists():
                logger.debug("Skills directory does not exist")
                return ""

            # Collect all skill files
            all_skill_files: list[Path] = []
            for ext in self.ALLOWED_EXTENSIONS:
                all_skill_files.extend(self.SKILLS_DIR.glob(f"*{ext}"))

            if not all_skill_files:
                logger.debug("No skill files found")
                return ""

            skill_files = self._filter_for_command(all_skill_files, command)

            # Sort for consistent ordering
            skill_files.sort()

            # Build concatenated context
            context_parts = []
            total_chars = 0

            for skill_file in skill_files:
                try:
                    # Read file content with UTF-8 encoding
                    content = skill_file.read_text(encoding="utf-8")

                    # Format with header
                    header = f"=== {skill_file.name} ==="
                    formatted = f"{header}\n{content}\n\n"

                    # If the file fits in full, take it whole. Otherwise we
                    # partially load it (header + as much body as fits) and
                    # stop. Stopping entirely -- the old behavior -- silently
                    # dropped the m-skills entirely whenever the next file
                    # was bigger than the remaining budget, which made the
                    # per-command router pointless in production.
                    if total_chars + len(formatted) <= self.MAX_CONTEXT_CHARS:
                        context_parts.append(formatted)
                        total_chars += len(formatted)
                        continue

                    remaining = self.MAX_CONTEXT_CHARS - total_chars
                    # Always keep the header visible so the LLM knows which
                    # file got cut. ``header_block`` is small (~30 chars), so
                    # if even that does not fit we just stop -- anything else
                    # would be misleading garbage with no provenance.
                    header_block = f"{header}\n"
                    if remaining <= len(header_block) + 32:
                        context_parts.append(
                            f"\n[TRUNCATED: Context exceeded "
                            f"{self.MAX_CONTEXT_CHARS} characters]"
                        )
                        break

                    body_budget = remaining - len(header_block) - 64  # leave room for notice
                    partial_body = content[:body_budget].rstrip()
                    context_parts.append(
                        f"{header_block}{partial_body}\n"
                        f"[TRUNCATED: file cut to fit "
                        f"{self.MAX_CONTEXT_CHARS}-char budget]\n\n"
                    )
                    total_chars = self.MAX_CONTEXT_CHARS
                    break

                except Exception as e:
                    logger.error("Failed to read skill file %s: %s", skill_file.name, e)
                    continue

            result = "".join(context_parts)
            logger.debug("Retrieved skill context: %d characters", len(result))
            return result

        except Exception as e:
            logger.error("Failed to retrieve skill context: %s", e, exc_info=True)
            return ""

    def _filter_for_command(
        self,
        files: list[Path],
        command: str | None,
    ) -> list[Path]:
        """Pick which skill files to load for a given command.

        Identity files always pass through. ``m*`` skill files only pass
        through when their ``mNN_`` (or ``mNN.``) prefix is listed under
        ``command`` in :attr:`COMMAND_SKILL_MAP`. Unknown commands and
        ``None`` fall back to "load everything" so the legacy single-call
        site keeps working.
        """
        if command is None or command not in self.COMMAND_SKILL_MAP:
            return list(files)

        allowed_prefixes = self.COMMAND_SKILL_MAP[command]

        def _is_identity(name: str) -> bool:
            stem = Path(name).stem.upper()
            return any(stem.startswith(p) for p in self.IDENTITY_FILE_PREFIXES)

        def _matches_command(name: str) -> bool:
            stem = Path(name).stem
            return any(
                stem == prefix
                or stem.startswith(f"{prefix}_")
                or stem.startswith(f"{prefix}.")
                for prefix in allowed_prefixes
            )

        return [
            f for f in files
            if _is_identity(f.name) or _matches_command(f.name)
        ]
