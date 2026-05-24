"""Manages per-user conversational history for the Telegram Web3 Bot.

This module provides the ContextManager class, which stores and retrieves
the last 5 message exchanges per user using python-telegram-bot's built-in
context.user_data dictionary. The implementation requires no external
dependencies and gracefully handles all storage/retrieval failures.

Usage:
    from web3_crew.context_manager import ContextManager

    # Retrieve history and augment current message
    augmented_input = ContextManager.get_augmented_input(
        context.user_data,
        "What is ETH?",
        user_id=12345
    )

    # Store exchange after bot responds
    ContextManager.store_exchange(
        context.user_data,
        "What is ETH?",
        "Ethereum is a blockchain platform...",
        user_id=12345
    )
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from html import unescape

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages per-user conversational history using python-telegram-bot's user_data.

    This class provides stateless utility methods for storing and retrieving
    conversational history. All operations use the user_data dictionary passed
    as a parameter, with no instance state maintained.

    Constants:
        MAX_EXCHANGES: Maximum number of exchanges to store per user (5)
        MAX_HISTORY_CHARS: Maximum total characters in formatted history (1000)
        MAX_REPLY_CHARS: Maximum characters per bot reply before truncation (200)
        HISTORY_KEY: Key used to store history in user_data dictionary
    """

    MAX_EXCHANGES: int = 5
    MAX_HISTORY_CHARS: int = 1000
    MAX_REPLY_CHARS: int = 200
    HISTORY_KEY: str = "conversation_history"

    @staticmethod
    def get_augmented_input(
        user_data: dict,
        current_message: str,
        user_id: int
    ) -> str:
        """Retrieve history and prepend to current message.

        This method retrieves the user's conversational history from user_data,
        formats it into a readable string, and prepends it to the current message.
        If no history exists or retrieval fails, returns only the current message.

        Args:
            user_data: The context.user_data dictionary for this user
            current_message: The raw user message from update.message.text
            user_id: Telegram user ID (used for logging only)

        Returns:
            Augmented input string with format:
            - If history exists: "Previous Chat:\\nUser: ...\\nBot: ...\\n\\nCurrent Prompt: {message}"
            - If no history: "{message}"

        Side Effects:
            - Logs INFO on successful retrieval with history size
            - Logs ERROR if retrieval from user_data fails
        """
        try:
            history = user_data.get(ContextManager.HISTORY_KEY, [])
            
            if not history:
                logger.info(f"No history found for user {user_id}, returning unaugmented input")
                return current_message
            
            formatted_history = ContextManager._format_history(history)
            logger.info(f"Retrieved history for user {user_id} (size: {len(history)}/{ContextManager.MAX_EXCHANGES})")
            
            return f"{formatted_history}\n\nCurrent Prompt: {current_message}"
            
        except Exception as e:
            logger.error(f"Failed to retrieve history for user {user_id}: {e}")
            return current_message

    @staticmethod
    def store_exchange(
        user_data: dict,
        user_message: str,
        bot_reply: str,
        user_id: int
    ) -> None:
        """Store a completed exchange in user's history.

        This method appends a new exchange to the user's conversational history,
        enforces the MAX_EXCHANGES limit by removing oldest exchanges, and
        truncates history if it exceeds MAX_HISTORY_CHARS.

        Args:
            user_data: The context.user_data dictionary for this user
            user_message: The original user message (not augmented)
            bot_reply: The bot's response text
            user_id: Telegram user ID (used for logging only)

        Side Effects:
            - Appends exchange to user_data[HISTORY_KEY]
            - Removes oldest exchange if count exceeds MAX_EXCHANGES
            - Truncates history if total chars exceed MAX_HISTORY_CHARS
            - Logs INFO on successful storage with history size
            - Logs ERROR on storage failure but never raises exceptions
            - Logs DEBUG when truncation occurs
        """
        try:
            # Initialize history if not exists
            if ContextManager.HISTORY_KEY not in user_data:
                user_data[ContextManager.HISTORY_KEY] = []
            
            history = user_data[ContextManager.HISTORY_KEY]
            
            # Clean bot reply (strip HTML, decode entities, truncate)
            cleaned_reply = ContextManager._clean_bot_reply(bot_reply)
            
            # Create exchange with timestamp
            exchange = {
                "user_message": user_message,
                "bot_reply": cleaned_reply,
                "timestamp": datetime.now().isoformat()
            }
            
            # Append new exchange
            history.append(exchange)
            
            # Enforce MAX_EXCHANGES limit (FIFO)
            if len(history) > ContextManager.MAX_EXCHANGES:
                removed = history.pop(0)
                logger.debug(f"Evicted oldest exchange for user {user_id} (timestamp: {removed['timestamp']})")
            
            # Truncate history if exceeds MAX_HISTORY_CHARS
            original_length = len(history)
            while len(ContextManager._format_history(history)) > ContextManager.MAX_HISTORY_CHARS and len(history) > 1:
                removed = history.pop(0)
                logger.debug(f"Truncated history for user {user_id}: removed exchange from {removed['timestamp']}")
            
            if len(history) < original_length:
                logger.debug(f"History truncation for user {user_id}: {original_length} -> {len(history)} exchanges")
            
            # Store back to user_data
            user_data[ContextManager.HISTORY_KEY] = history
            
            logger.info(f"Stored exchange for user {user_id} (history size: {len(history)}/{ContextManager.MAX_EXCHANGES})")
            
        except Exception as e:
            logger.error(f"Failed to store exchange for user {user_id}: {e}")
            # Continue execution - storage failure is non-fatal

    @staticmethod
    def _format_history(exchanges: list[dict]) -> str:
        """Format exchange list into readable history string.

        Args:
            exchanges: List of exchange dictionaries with keys:
                - user_message: str
                - bot_reply: str
                - timestamp: str (ISO 8601 format)

        Returns:
            Formatted string with pattern:
            "Previous Chat:\\nUser: {message}\\nBot: {reply}\\nUser: {message}\\nBot: {reply}\\n"
        """
        if not exchanges:
            return ""
        
        lines = ["Previous Chat:"]
        for exchange in exchanges:
            lines.append(f"User: {exchange['user_message']}")
            lines.append(f"Bot: {exchange['bot_reply']}")
        
        return "\n".join(lines)

    @staticmethod
    def _clean_bot_reply(reply: str) -> str:
        """Strip HTML tags, decode entities, truncate to MAX_REPLY_CHARS.

        This method cleans bot replies before storage by:
        1. Stripping HTML tags using regex pattern <[^>]+>
        2. Decoding HTML entities (e.g., &amp; to &, &lt; to <)
        3. Truncating to MAX_REPLY_CHARS Unicode code points with "..." suffix

        Args:
            reply: Raw bot reply text (may contain HTML tags and entities)

        Returns:
            Cleaned reply text, truncated if necessary
        """
        # Strip HTML tags
        text = re.sub(r'<[^>]+>', '', reply)
        
        # Decode HTML entities
        text = unescape(text)
        
        # Truncate to MAX_REPLY_CHARS (Unicode code points, not bytes)
        if len(text) > ContextManager.MAX_REPLY_CHARS:
            text = text[:ContextManager.MAX_REPLY_CHARS] + "..."
        
        return text
