"""
generate_session.py
Run this LOCALLY (on your PC) to generate String Sessions for each phone number.
String Sessions allow the bot to run on cloud without re-authentication.

Usage:
    python generate_session.py
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

print("=" * 50)
print("  TELEGRAM SESSION STRING GENERATOR")
print("  Run this on your LOCAL PC only!")
print("=" * 50)

async def generate_session():
    print("\n📱 Get your API credentials from https://my.telegram.org/apps")
    
    api_id = int(input("\nEnter API ID: ").strip())
    api_hash = input("Enter API Hash: ").strip()
    phone = input("Enter Phone Number (with country code, e.g. +919876543210): ").strip()
    
    print(f"\n🔗 Connecting to Telegram for {phone}...")
    
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start(phone=phone)
        
        session_string = client.session.save()
        
        print("\n" + "=" * 60)
        print("✅ SUCCESS! Copy this SESSION STRING to your .env file:")
        print("=" * 60)
        print(f"\n{session_string}\n")
        print("=" * 60)
        print("\n⚠️  KEEP THIS SECRET! Anyone with this string can access your account.")
        print("   Add it to SESSION_STRING_1 or SESSION_STRING_2 in your .env file")
        
        # Save to file for convenience
        fname = f"session_{phone.replace('+', '').replace(' ', '')}.txt"
        with open(fname, "w") as f:
            f.write(session_string)
        print(f"\n💾 Also saved to: {fname}")

if __name__ == "__main__":
    asyncio.run(generate_session())
