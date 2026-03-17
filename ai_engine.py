"""
ai_engine.py
Handles all AI response generation using Google Gemini API.
"""

import google.generativeai as genai
genai.configure  # ensure v1 endpoint used
import asyncio
import logging
import random
import re
from typing import Optional

logger = logging.getLogger(__name__)


class AIEngine:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash-latest",
            generation_config=genai.types.GenerationConfig(
                temperature=0.92,       # High creativity for natural responses
                top_p=0.95,
                top_k=40,
                max_output_tokens=200,  # Keep responses short like real chat
            ),
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
            ]
        )
        # Per-conversation memory: {chat_id: [messages]}
        self.conversation_history: dict = {}
        self.MAX_HISTORY = 10  # Keep last 10 exchanges per chat

    def _get_history(self, chat_id: int) -> list:
        return self.conversation_history.get(chat_id, [])

    def _add_to_history(self, chat_id: int, role: str, text: str):
        if chat_id not in self.conversation_history:
            self.conversation_history[chat_id] = []
        self.conversation_history[chat_id].append({
            "role": role,
            "parts": [{"text": text}]
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
        
        # Only add typos 15% of the time
        if random.random() > 0.15:
            return text
        
        # Common Hinglish typos
        typo_map = {
            "kya": "kyaa",
            "bhai": "bhia",
            "nahi": "nhi",
            "yaar": "yar",
            "sahi": "sahi",
            "arre": "arre",
            "haan": "haan",
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
        Generate a human-like response using Gemini.
        Returns None if bot decides to stay silent.
        """
        try:
            # Build the full prompt with context
            context_str = ""
            if context_messages:
                context_str = "\n".join([
                    f"{m['sender']}: {m['text']}" 
                    for m in context_messages[-5:]  # Last 5 messages for context
                ])

            full_prompt = f"""{system_prompt}

---
CURRENT GROUP CHAT CONTEXT (recent messages):
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

            # Add to history and generate
            history = self._get_history(chat_id)
            
            chat_session = self.model.start_chat(history=history)
            
            message_content = []
            if image_path:
                try:
                    import PIL.Image
                    img = PIL.Image.open(image_path)
                    message_content.append(img)
                except Exception as e:
                    logger.error(f"Error loading image: {e}")
            message_content.append(full_prompt)
            
            response = await asyncio.to_thread(
                chat_session.send_message, message_content
            )
            
            reply_text = response.text.strip()
            
            # Check if bot wants to skip
            if "[SKIP]" in reply_text or reply_text == "[SKIP]":
                logger.info("AI decided to skip this message")
                return None
            
            # Clean up response
            reply_text = self._clean_response(reply_text, personality)
            reply_text = self._add_human_imperfections(reply_text, personality)
            
            # Update history
            self._add_to_history(chat_id, "user", f"{sender_name}: {user_message}")
            self._add_to_history(chat_id, "model", reply_text)
            
            return reply_text
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None

    def _clean_response(self, text: str, personality: dict) -> str:
        """Remove AI artifacts and enforce character limits"""
        # Remove asterisks from markdown bold/italic
        text = re.sub(r'\*+', '', text)
        # Remove hashtags
        text = re.sub(r'#\w+', '', text)
        # Remove "As an AI" type phrases
        ai_phrases = [
            "as an ai", "i am an ai", "as a language model",
            "i'm an ai", "as your ai", "mein ek ai hoon"
        ]
        for phrase in ai_phrases:
            text = re.sub(phrase, '', text, flags=re.IGNORECASE)
        
        # Enforce max length
        max_len = personality.get("typing_style", {}).get("max_response_length", 150)
        if len(text) > max_len:
            # Cut at last sentence/word boundary
            text = text[:max_len].rsplit(' ', 1)[0]
        
        return text.strip()

    def should_reply(self, reply_chance: float) -> bool:
        """Randomly decide whether to reply (simulate human selectivity)"""
        return random.random() < reply_chance


class ConversationMemory:
    """Stores recent chat messages for context"""
    
    def __init__(self, max_messages: int = 20):
        self.messages: dict = {}  # {chat_id: [messages]}
        self.max_messages = max_messages
    
    def add_message(self, chat_id: int, sender: str, text: str):
        if chat_id not in self.messages:
            self.messages[chat_id] = []
        self.messages[chat_id].append({
            "sender": sender,
            "text": text[:200]  # Limit stored text
        })
        # Keep only recent messages
        if len(self.messages[chat_id]) > self.max_messages:
            self.messages[chat_id] = self.messages[chat_id][-self.max_messages:]
    
    def get_context(self, chat_id: int, last_n: int = 7) -> list:
        return self.messages.get(chat_id, [])[-last_n:]
