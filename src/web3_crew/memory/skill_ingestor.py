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
    MAX_CONTEXT_CHARS: Final[int] = 4000

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

    def get_skill_context(self) -> str:
        """Retrieve concatenated content of all skill files.

        Returns:
            Formatted string with all skill content, or empty string
            if no skills exist or on error. Format:

            === filename1.md ===
            [content]

            === filename2.md ===
            [content]

            [TRUNCATED: Context exceeded 4000 characters]
        """
        try:
            # Check if skills directory exists
            if not self.SKILLS_DIR.exists():
                logger.debug("Skills directory does not exist")
                return ""

            # Collect all skill files
            skill_files = []
            for ext in self.ALLOWED_EXTENSIONS:
                skill_files.extend(self.SKILLS_DIR.glob(f"*{ext}"))

            if not skill_files:
                logger.debug("No skill files found")
                return ""

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

                    # Check if adding this would exceed limit
                    if total_chars + len(formatted) > self.MAX_CONTEXT_CHARS:
                        # Add truncation notice
                        context_parts.append(
                            "\n[TRUNCATED: Context exceeded 4000 characters]"
                        )
                        break

                    context_parts.append(formatted)
                    total_chars += len(formatted)

                except Exception as e:
                    logger.error("Failed to read skill file %s: %s", skill_file.name, e)
                    continue

            result = "".join(context_parts)
            logger.debug("Retrieved skill context: %d characters", len(result))
            return result

        except Exception as e:
            logger.error("Failed to retrieve skill context: %s", e, exc_info=True)
            return ""
