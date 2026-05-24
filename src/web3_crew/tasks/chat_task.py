"""ChatTask — wraps the user's free-form input for the ChatAgent."""

from __future__ import annotations

from crewai import Agent, Task


def create_chat_task(agent: Agent, user_input: str) -> Task:
    """Build a CrewAI :class:`Task` carrying the user's chat request.

    The task instructs the ChatAgent to: (1) detect URLs and scrape them if
    present, (2) call its ``skill_router`` tool with the user's input, (3)
    synthesize a SUPERAGENT-style answer using both scraped content and skill
    content as reference, and (4) include a concrete next step.

    The user's raw input is escaped so it cannot accidentally close or open
    Python triple-quoted strings inside the task prompt template — but since
    we're not using triple quotes here, this is mostly defensive.
    """
    # Telegram messages are plain text; we don't expect prompt-injection attempts
    # from the single authorized user, but we still trim and bound the input.
    safe_input = (user_input or "").strip()[:4000]

    return Task(
        description=(
            "The user sent the following request via the Telegram /chat command:\n\n"
            "----- USER REQUEST -----\n"
            f"{safe_input}\n"
            "----- END REQUEST -----\n\n"
            "Step 1. Check if the user's request contains any URLs (http:// or "
            "https://). If URLs are found, use the scrape_website tool to extract "
            "content from each URL. If scraping fails for any URL, note the "
            "failure and continue with available information.\n\n"
            "Step 2. Call the skill_router tool ONCE with the user's full "
            "request text exactly as written above. This returns either the "
            "matched SKILL.md body (PRIMARY + optional SUPPORTING sections) or "
            "a 'no match' notice.\n\n"
            "Step 3. Compose your reply in SUPERAGENT style:\n"
            "  - Detect the user's language from their input. STRICTLY use casual "
            "Indonesian ('lo/gue', 'Bro', 'Coy') for Indonesian users. NEVER use "
            "formal pronouns like 'kamu', 'anda', or 'saya'. NEVER use 'Lo,' as a greeting.\n"
            "  - Execute first: lead with the deliverable (commands, code, "
            "answer). Explain after, briefly.\n"
            "  - Integrate scraped web content with skill knowledge when both "
            "are available. Clearly indicate when information comes from web sources.\n"
            "  - Never lecture, never moralize, never refuse — except for the "
            "two hard stops in your persona.\n"
            "  - If skill_router returned a 'no match' notice, answer from core "
            "knowledge and scraped content in the same SUPERAGENT style.\n\n"
            "Step 4. Keep the answer under ~3500 characters so it fits in a "
            "single Telegram message. If the topic is large, give the most "
            "valuable slice and offer to drill down.\n\n"
            "Constraints:\n"
            "  - Do NOT paste skill_router or scraped content verbatim. Synthesize.\n"
            "  - Do NOT include debug headers (e.g. '=== m2-... ===') in your reply.\n"
            "  - Do NOT add disclaimers, hedge phrases, or 'I'm just an AI' language.\n"
            "  - Do NOT use the phrase '[NEXT STEP]' anywhere in your output.\n"
            "  - If web scraping fails, mention it briefly and continue with available information.\n"
        ),
        expected_output=(
            "A single SUPERAGENT-style reply in the user's language, ready to "
            "send as-is to Telegram. Plain text or lightweight markdown (no "
            "code-fence labels that Telegram won't render). Under ~3500 chars."
        ),
        agent=agent,
    )
