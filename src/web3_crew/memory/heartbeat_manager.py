"""Session Heartbeat Manager for Web3 Crew AI.

Implements the HEARTBEAT.md protocol for session continuity tracking,
pending task detection, and token discipline management.

This module is designed as a non-invasive add-on that integrates with
the existing ContextManager without requiring external dependencies.

Usage:
    from web3_crew.memory import SessionHeartbeat

    # Initialize at bot startup
    heartbeat = SessionHeartbeat()

    # Check session state before processing message
    notification = await heartbeat.check_session_state(
        user_data=context.user_data,
        user_id=user_id
    )
    if notification:
        await update.message.reply_text(notification)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TypedDict

logger = logging.getLogger(__name__)


class SessionState(TypedDict, total=False):
    """Internal session state tracking structure."""
    session_start: str  # ISO 8601 timestamp
    goal: str  # Stated objective
    active_skill: list[str]  # Loaded modules (e.g., ["m4", "m6"])
    decisions: list[str]  # Key decisions made
    blockers: list[str]  # Current blockers
    files_touched: list[str]  # Files modified
    tokens_used: int  # Approximate token count
    last_activity: str  # ISO 8601 timestamp
    pending_tasks: list[dict]  # Tasks with timestamp and description


class SessionHeartbeat:
    """Manages session continuity and token discipline per HEARTBEAT.md protocol.

    This class provides stateless utility methods for tracking session state,
    detecting stale tasks, and managing token budget awareness. All operations
    use the user_data dictionary passed as parameters.

    Constants:
        SESSION_KEY: Key for storing session state in user_data
        PENDING_TASK_THRESHOLD_HOURS: Hours before flagging stale task (24)
        SESSION_GAP_THRESHOLD_DAYS: Days before showing context recap (7)
        TOKEN_WARNING_THRESHOLD: Approximate token count before suggesting new session (150000)
    """

    SESSION_KEY: str = "session_state"
    PENDING_TASK_THRESHOLD_HOURS: int = 24
    SESSION_GAP_THRESHOLD_DAYS: int = 7
    TOKEN_WARNING_THRESHOLD: int = 150000

    def __init__(self) -> None:
        """Initialize SessionHeartbeat manager."""
        logger.info("SessionHeartbeat manager initialized")

    async def check_session_state(
        self,
        user_data: dict,
        user_id: int
    ) -> str | None:
        """Check session state and return notification if needed.

        This method implements the "Session Continuity Triggers" from HEARTBEAT.md:
        - Flags pending tasks older than 24 hours
        - Offers resume for incomplete deployments
        - Shows context recap after 7+ day gaps

        Args:
            user_data: The context.user_data dictionary for this user
            user_id: Telegram user ID (used for logging)

        Returns:
            Notification string if action needed, None otherwise
        """
        try:
            session = user_data.get(self.SESSION_KEY)
            
            if not session:
                # First session - initialize
                self._initialize_session(user_data, user_id)
                return None

            # Check for stale pending tasks
            stale_task_msg = self._check_pending_tasks(session, user_id)
            if stale_task_msg:
                return stale_task_msg

            # Check for session gap (7+ days)
            gap_msg = self._check_session_gap(session, user_id)
            if gap_msg:
                return gap_msg

            # Update last activity
            session["last_activity"] = datetime.now().isoformat()
            user_data[self.SESSION_KEY] = session

            return None

        except Exception as e:
            logger.error(f"Failed to check session state for user {user_id}: {e}")
            return None

    def track_activity(
        self,
        user_data: dict,
        user_id: int,
        activity_type: str,
        details: str | None = None
    ) -> None:
        """Track user activity in session state.

        Args:
            user_data: The context.user_data dictionary for this user
            user_id: Telegram user ID
            activity_type: Type of activity ("goal", "decision", "blocker", "file_touched")
            details: Activity details
        """
        try:
            session = user_data.get(self.SESSION_KEY)
            if not session:
                self._initialize_session(user_data, user_id)
                session = user_data[self.SESSION_KEY]

            # Update activity timestamp
            session["last_activity"] = datetime.now().isoformat()

            # Track specific activity types
            if activity_type == "goal" and details:
                session["goal"] = details
            elif activity_type == "decision" and details:
                session["decisions"].append(details)
            elif activity_type == "blocker" and details:
                session["blockers"].append(details)
            elif activity_type == "file_touched" and details:
                if details not in session["files_touched"]:
                    session["files_touched"].append(details)

            user_data[self.SESSION_KEY] = session
            logger.debug(f"Tracked activity for user {user_id}: {activity_type}")

        except Exception as e:
            logger.error(f"Failed to track activity for user {user_id}: {e}")

    def add_pending_task(
        self,
        user_data: dict,
        user_id: int,
        task_description: str
    ) -> None:
        """Add a pending task to session state.

        Args:
            user_data: The context.user_data dictionary for this user
            user_id: Telegram user ID
            task_description: Description of the pending task
        """
        try:
            session = user_data.get(self.SESSION_KEY)
            if not session:
                self._initialize_session(user_data, user_id)
                session = user_data[self.SESSION_KEY]

            task = {
                "description": task_description,
                "timestamp": datetime.now().isoformat()
            }
            session["pending_tasks"].append(task)
            user_data[self.SESSION_KEY] = session

            logger.info(f"Added pending task for user {user_id}: {task_description}")

        except Exception as e:
            logger.error(f"Failed to add pending task for user {user_id}: {e}")

    def clear_pending_task(
        self,
        user_data: dict,
        user_id: int,
        task_description: str
    ) -> None:
        """Remove a completed task from pending tasks.

        Args:
            user_data: The context.user_data dictionary for this user
            user_id: Telegram user ID
            task_description: Description of the task to remove
        """
        try:
            session = user_data.get(self.SESSION_KEY)
            if not session:
                return

            session["pending_tasks"] = [
                task for task in session["pending_tasks"]
                if task["description"] != task_description
            ]
            user_data[self.SESSION_KEY] = session

            logger.info(f"Cleared pending task for user {user_id}: {task_description}")

        except Exception as e:
            logger.error(f"Failed to clear pending task for user {user_id}: {e}")

    def estimate_tokens(
        self,
        user_data: dict,
        user_id: int,
        message_length: int
    ) -> str | None:
        """Estimate token usage and suggest new session if needed.

        Args:
            user_data: The context.user_data dictionary for this user
            user_id: Telegram user ID
            message_length: Length of current message in characters

        Returns:
            Warning message if token threshold exceeded, None otherwise
        """
        try:
            session = user_data.get(self.SESSION_KEY)
            if not session:
                return None

            # Rough estimation: 1 token ˜ 4 characters
            estimated_tokens = message_length // 4
            session["tokens_used"] = session.get("tokens_used", 0) + estimated_tokens

            user_data[self.SESSION_KEY] = session

            # Check if threshold exceeded
            if session["tokens_used"] > self.TOKEN_WARNING_THRESHOLD:
                logger.info(f"Token threshold exceeded for user {user_id}: {session['tokens_used']}")
                return "Lanjut di sesi baru biar context fresh?"

            return None

        except Exception as e:
            logger.error(f"Failed to estimate tokens for user {user_id}: {e}")
            return None

    def _initialize_session(self, user_data: dict, user_id: int) -> None:
        """Initialize a new session state."""
        session: SessionState = {
            "session_start": datetime.now().isoformat(),
            "goal": "",
            "active_skill": [],
            "decisions": [],
            "blockers": [],
            "files_touched": [],
            "tokens_used": 0,
            "last_activity": datetime.now().isoformat(),
            "pending_tasks": []
        }
        user_data[self.SESSION_KEY] = session
        logger.info(f"Initialized new session for user {user_id}")

    def _check_pending_tasks(self, session: SessionState, user_id: int) -> str | None:
        """Check for stale pending tasks (>24 hours old)."""
        try:
            now = datetime.now()
            threshold = timedelta(hours=self.PENDING_TASK_THRESHOLD_HOURS)

            for task in session.get("pending_tasks", []):
                task_time = datetime.fromisoformat(task["timestamp"])
                if now - task_time > threshold:
                    task_desc = task["description"]
                    task_date = task_time.strftime("%Y-%m-%d")
                    logger.info(f"Stale task detected for user {user_id}: {task_desc}")
                    return f"Catatan: {task_desc} dari {task_date} masih open. Lanjutin atau drop?"

            return None

        except Exception as e:
            logger.error(f"Failed to check pending tasks for user {user_id}: {e}")
            return None

    def _check_session_gap(self, session: SessionState, user_id: int) -> str | None:
        """Check for session gap (>7 days) and offer context recap."""
        try:
            now = datetime.now()
            last_activity = datetime.fromisoformat(session["last_activity"])
            gap = now - last_activity

            if gap > timedelta(days=self.SESSION_GAP_THRESHOLD_DAYS):
                goal = session.get("goal", "N/A")
                last_decision = session.get("decisions", ["N/A"])[-1] if session.get("decisions") else "N/A"
                open_items = len(session.get("pending_tasks", []))

                logger.info(f"Session gap detected for user {user_id}: {gap.days} days")
                return (
                    f"Last session: {goal} | "
                    f"Last decision: {last_decision} | "
                    f"Open: {open_items} tasks"
                )

            return None

        except Exception as e:
            logger.error(f"Failed to check session gap for user {user_id}: {e}")
            return None
