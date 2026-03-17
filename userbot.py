"""
userbot.py
Core userbot logic — logs in with real phone number, listens to groups,
and responds with AI-generated human-like messages.
"""

import asyncio
import logging
import os
import random
import time
from typing import Optional

from telethon import TelegramClient, events
from telethon.tl.types import User, Chat, Channel
from telethon.errors import FloodWaitError, UserDeactivatedBanError

from ai_engine import AIEngine, ConversationMemory
from personalities import get_personality

logger = logging.getLogger(__name__)


class HumanBot:
    """
    A single userbot instance that mimics a human Telegram user.
    """

    def __init__(
        self,
        bot_key: str,
        api_id: int,
        api_hash: str,
        phone: str,
        session_string: str,
        ai_engine: AIEngine,
        target_groups: list,
        config: dict,
    ):
        self.bot_key = bot_key
        self.personality = get_personality(bot_key)
        self.config = config
        self.ai_engine = ai_engine
        self.memory = ConversationMemory(max_messages=25)
        self.target_groups = target_groups
        self._last_reply_time: dict = {}  # {chat_id: timestamp}
        self._cooldown_seconds = 30  # Min time between replies in same chat

        # Create Telethon client
        session_path = f"sessions/{bot_key}"
        os.makedirs("sessions", exist_ok=True)
        
        if session_string and session_string.strip():
            from telethon.sessions import StringSession
            self.client = TelegramClient(
                StringSession(session_string.strip()),
                api_id,
                api_hash,
                device_model="Samsung Galaxy S24",
                system_version="Android 14",
                app_version="10.3.2",
                lang_code="en",
                system_lang_code="en-US",
            )
        else:
            self.client = TelegramClient(
                session_path,
                api_id,
                api_hash,
                device_model="Samsung Galaxy S24",
                system_version="Android 14",
                app_version="10.3.2",
                lang_code="en",
                system_lang_code="en-US",
            )
        
        self.phone = phone
        self._running = False

    async def start(self):
        """Start the userbot and connect to Telegram"""
        logger.info(f"[{self.bot_key}] Starting userbot as {self.personality['name']}...")
        
        await self.client.start(phone=self.phone)
        me = await self.client.get_me()
        logger.info(f"[{self.bot_key}] Logged in as: {me.first_name} (@{me.username})")
        
        # Register event handlers
        self._register_handlers()
        self._running = True
        logger.info(f"[{self.bot_key}] Bot is now listening in {len(self.target_groups)} groups...")

    def _register_handlers(self):
        """Register all message event handlers"""
        
        @self.client.on(events.NewMessage(chats=self.target_groups))
        async def on_group_message(event):
            await self._handle_group_message(event)

    async def _handle_group_message(self, event):
        """Main message handler — decides whether and how to reply"""
        try:
            # Don't reply to own messages
            me = await self.client.get_me()
            if event.sender_id == me.id:
                return

            message = event.message
            text = message.text or message.caption or ""
            has_media = False
            image_path = None
            
            if message.photo:
                has_media = True
                os.makedirs("downloads", exist_ok=True)
                image_path = await message.download_media(file=f"downloads/{event.id}.jpg")
                if not text:
                    text = "[User sent an image]"
            elif not text or len(text.strip()) < 3:
                return

            # Get sender info
            sender = await event.get_sender()
            if isinstance(sender, User):
                sender_name = sender.first_name or "Someone"
                # Don't reply to bots
                if sender.bot:
                    return
            else:
                sender_name = "Member"

            chat_id = event.chat_id
            
            # Store message in memory regardless of whether we reply
            self.memory.add_message(chat_id, sender_name, text)

            # Decide whether to reply
            should_reply = self._should_reply_to_message(event, text, me)
            if not should_reply:
                return

            # Check cooldown (don't spam same chat)
            if not self._check_cooldown(chat_id):
                logger.debug(f"[{self.bot_key}] Cooldown active for chat {chat_id}")
                return

            # Human-like delay before replying (simulate reading)
            min_delay = int(self.config.get("MIN_REPLY_DELAY", 8))
            max_delay = int(self.config.get("MAX_REPLY_DELAY", 35))
            delay = random.uniform(min_delay, max_delay)
            
            logger.info(f"[{self.bot_key}] Will reply in {delay:.1f}s to: {text[:50]}...")
            await asyncio.sleep(delay)

            # Get context from memory
            context = self.memory.get_context(chat_id, last_n=7)

            # Generate AI response
            reply = await self.ai_engine.generate_response(
                system_prompt=self.personality["system_prompt"],
                user_message=text,
                sender_name=sender_name,
                chat_id=chat_id,
                personality=self.personality,
                context_messages=context,
                image_path=image_path
            )

            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception as e:
                    logger.warning(f"Failed to delete {image_path}: {e}")

            if reply:
                await self._send_with_typing(event, reply)
                self._update_cooldown(chat_id)
                # Add own message to memory
                self.memory.add_message(chat_id, self.personality["name"], reply)

        except FloodWaitError as e:
            logger.warning(f"[{self.bot_key}] FloodWait: sleeping {e.seconds}s")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"[{self.bot_key}] Error handling message: {e}", exc_info=True)

    def _should_reply_to_message(self, event, text: str, me) -> bool:
        """
        Smart decision: should we reply to this message?
        Returns True if bot should respond.
        """
        reply_chance = float(self.config.get("REPLY_CHANCE", 0.4))
        
        # Always reply if directly mentioned by name
        bot_name = self.personality["name"].lower()
        personality_triggers = self.personality.get("display_trigger", [])
        
        text_lower = text.lower()
        
        # Check if mentioned by name or username
        if any(trigger in text_lower for trigger in personality_triggers):
            logger.info(f"[{self.bot_key}] Mentioned directly — will reply")
            return True
        
        # Check if it's a reply to our message
        if event.message.reply_to_msg_id:
            # We'll reply to replies to our messages with higher probability
            return random.random() < 0.75
        
        # Check for questions (more likely to answer questions)
        question_indicators = ["?", "kya", "kaise", "kyun", "kaun", "kab", "kahan", "batao", "bolo"]
        if any(ind in text_lower for ind in question_indicators):
            return random.random() < (reply_chance * 1.5)
        
        # Random chance for other messages
        return self.ai_engine.should_reply(reply_chance)

    def _check_cooldown(self, chat_id: int) -> bool:
        """Check if enough time has passed since last reply in this chat"""
        last_reply = self._last_reply_time.get(chat_id, 0)
        return (time.time() - last_reply) >= self._cooldown_seconds

    def _update_cooldown(self, chat_id: int):
        self._last_reply_time[chat_id] = time.time()

    async def _send_with_typing(self, event, text: str):
        """
        Simulate human typing:
        1. Send 'typing...' indicator
        2. Wait based on message length
        3. Send actual message
        """
        typing_speed = int(self.config.get("TYPING_SPEED", 12))  # chars/sec
        typing_duration = min(len(text) / typing_speed, 8)  # Max 8 seconds typing
        
        async with self.client.action(event.chat_id, "typing"):
            await asyncio.sleep(typing_duration)
        
        # Small random pause after stopping typing (very human)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        await event.reply(text)
        logger.info(f"[{self.bot_key}] Sent reply: {text[:60]}...")

    async def stop(self):
        """Gracefully stop the bot"""
        self._running = False
        await self.client.disconnect()
        logger.info(f"[{self.bot_key}] Disconnected.")
