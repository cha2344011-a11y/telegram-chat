"""
ai_engine.py
Handles all AI response generation using OpenAI ChatGPT API.
"""

from openai import AsyncOpenAI
import logging
import random
import re
from typing import Optional
import base64

logger = logging.getLogger(__name__)


class AIEngine:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model_name = "gpt-4o-mini"  # Cheap + fast + smart
        # Per-conversation memory: {chat_id: [messages]}
        self.conversation_history: dict = {}
        self.MAX_HISTORY = 10

    def _get_history(self, chat_id: int) -> list:
        return self.conversation_history.get(chat_id, [])

    def _add_to_history(self, chat_id: int, role: str, content):
        if chat_id not in self.conversation_history:
            self.conversation_history[chat_id] = []
        self.conversation_history[chat_id].append({
            "role": role,
            "content": content
        })
        # Keep only last MAX_HISTORY messages
        if len(self.conversation_history[chat_id]) > self.MAX_HISTORY * 2:
            self.conversation_history[chat_id] = \
                self.conversation_history[chat_id][-self.MAX_HISTORY * 2:]

    def _add_human_imperfections(self, text: str, personality: dict) -> str:
        """Add occasional typos and imperfections to make text more human"""
        typing_style = personality.get("typing_style", {})
        if not typing_style.get("occasional_typos", False):
            return text
        if random.random() > 0.15:
            return text
        typo_map = {
            "kya": "kyaa",
            "bhai": "bhia",
            "nahi": "nhi",
            "yaar": "yar",
        }
        for correct, typo in typo_map.items():
            if correct in text.lower() and random.random() < 0.3:
                text = text.replace(correct, typo, 1)
                break
        return text

    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        sender_name: str,
        chat_id: int,
        personality: dict,
        context_messages: Optional[list] = None,
        image_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a human-like response using OpenAI GPT.
        Returns None if bot decides to stay silent.
        """
        try:
            # Build context string
            context_str = ""
            if context_messages:
                context_str = "\n".join([
                    f"{m['sender']}: {m['text']}"
                    for m in context_messages[-5:]
                ])

            user_prompt = f"""CURRENT GROUP CHAT CONTEXT (recent messages):
{context_str}

---
LATEST MESSAGE from {sender_name}:
"{user_message}"

---
INSTRUCTIONS:
- Reply naturally as your character in 1-3 lines maximum
- Do NOT start with the person's name
- Do NOT use quotation marks in your reply
- Write ONLY your reply, nothing else
- If the message isn't relevant to you or doesn't need response, reply with exactly: [SKIP]
- Reply in Hinglish (Hindi+English mix) naturally
"""

            # Build message content (with image if present)
            if image_path:
                try:
                    with open(image_path, "rb") as img_file:
                        img_data = base64.b64encode(img_file.read()).decode("utf-8")
                    user_content = [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_data}",
                                "detail": "low"
                            }
                        },
                        {"type": "text", "text": user_prompt}
                    ]
                except Exception as e:
                    logger.error(f"Error loading image: {e}")
                    user_content = user_prompt
            else:
                user_content = user_prompt

            # Build messages list with history
            history = self._get_history(chat_id)
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-10:])  # Last 10 messages for context
            messages.append({"role": "user", "content": user_content})

            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=200,
                temperature=0.92,
                top_p=0.95,
            )

            reply_text = response.choices[0].message.content.strip()

            # Check if bot wants to skip
            if "[SKIP]" in reply_text or reply_text == "[SKIP]":
                logger.info("AI decided to skip this message")
                return None

            # Clean up response
            reply_text = self._clean_response(reply_text, personality)
            reply_text = self._add_human_imperfections(reply_text, personality)

            # Update history
            self._add_to_history(chat_id, "user", f"{sender_name}: {user_message}")
            self._add_to_history(chat_id, "assistant", reply_text)

            return reply_text

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None

    def _clean_response(self, text: str, personality: dict) -> str:
        """Remove AI artifacts and enforce character limits"""
        text = re.sub(r'\*+', '', text)
        text = re.sub(r'#\w+', '', text)
        ai_phrases = [
            "as an ai", "i am an ai", "as a language model",
            "i'm an ai", "as your ai", "mein ek ai hoon"
        ]
        for phrase in ai_phrases:
            text = re.sub(phrase, '', text, flags=re.IGNORECASE)
        max_len = personality.get("typing_style", {}).get("max_response_length", 150)
        if len(text) > max_len:
            text = text[:max_len].rsplit(' ', 1)[0]
        return text.strip()

    def should_reply(self, reply_chance: float) -> bool:
        """Randomly decide whether to reply"""
        return random.random() < reply_chance


class ConversationMemory:
    """Stores recent chat messages for context"""

    def __init__(self, max_messages: int = 20):
        self.messages: dict = {}
        self.max_messages = max_messages

    def add_message(self, chat_id: int, sender: str, text: str):
        if chat_id not in self.messages:
            self.messages[chat_id] = []
        self.messages[chat_id].append({
            "sender": sender,
            "text": text[:200]
        })
        if len(self.messages[chat_id]) > self.max_messages:
            self.messages[chat_id] = self.messages[chat_id][-self.max_messages:]

    def get_context(self, chat_id: int, last_n: int = 7) -> list:
        return self.messages.get(chat_id, [])[-last_n:]
