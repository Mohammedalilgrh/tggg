import asyncio
import random
import os
import time
import json
import logging
from datetime import datetime, timedelta
from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, PeerFloodError,
    UserNotMutualContactError, UserChannelsTooMuchError,
    ChatAdminRequiredError, UserAlreadyParticipantError, SessionPasswordNeededError
)
from supabase import create_client
import sys

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_automation.log'),
        logging.StreamHandler()
    ]
)

class TelegramAutoBot:
    def __init__(self):
        # Environment variables
        self.api_id = os.getenv('API_ID', '21706160')
        self.api_hash = os.getenv('API_HASH', '548b91f0e7cd2e44bbee05190620d9f4')
        self.phone = os.getenv('PHONE_NUMBER', '+96407762476460')
        self.session_string = os.getenv('SESSION_STRING', '').strip()
        
        # Debug session string
        logging.info(f"Session string length: {len(self.session_string)}")
        logging.info(f"Session string: {self.session_string[:20]}...")
        
        # Supabase configuration
        supabase_url = os.getenv('SUPABASE_URL', 'https://apseoggiwlcdwzihfthz.supabase.co')
        supabase_key = os.getenv('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFwc2VvZ2dpd2xjZHd6aWhmdGh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5ODk2NzMsImV4cCI6MjA3NzU2NTY3M30.ZD47Gvm1cFc-oE2hJyoStWHuCvdXFlrxdrgBPucfW0Q')
        self.supabase = create_client(supabase_url, supabase_key)
        
        # Enhanced anti-ban settings 
        self.min_delay = 60
        self.max_delay = 180
        self.daily_add_limit = 150
        self.hourly_add_limit = 20
        self.session_add_limit = 30
        
        # Activity tracking
        self.adds_today = 0
        self.adds_this_hour = 0
        self.last_activity = datetime.now()
        self.session_start = datetime.now()
        
        # Initialize client - FIXED VERSION
        try:
            if self.session_string and len(self.session_string) > 10:
                self.client = TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash)
                logging.info("Client initialized with session string")
            else:
                self.client = TelegramClient('auto_session', self.api_id, self.api_hash)
                logging.info("Client initialized with file session")
        except Exception as e:
            logging.error(f"Client initialization failed: {e}")
            self.client = TelegramClient('auto_session', self.api_id, self.api_hash)
            
        # Load previous stats
        self.load_daily_stats()

    def load_daily_stats(self):
        """Load daily statistics from Supabase"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            result = self.supabase.table('daily_stats').select('*').eq('date', today).execute()
            if result.data:
                self.adds_today = result.data[0].get('adds_count', 0)
                logging.info(f"Loaded daily stats: {self.adds_today} adds today")
        except Exception as e:
            logging.error(f"Error loading stats: {e}")

    async def update_daily_stats(self):
        """Update daily statistics in Supabase"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            data = {
                'date': today,
                'adds_count': self.adds_today,
                'last_updated': datetime.now().isoformat()
            }
            existing = self.supabase.table('daily_stats').select('*').eq('date', today).execute()
            if existing.data:
                self.supabase.table('daily_stats').update(data).eq('date', today).execute()
            else:
                self.supabase.table('daily_stats').insert(data).execute()
            logging.info(f"Updated daily stats: {self.adds_today} adds")
        except Exception as e:
            logging.error(f"Error updating stats: {e}")

    async def safe_operation_delay(self):
        """Enhanced safety delay with random patterns"""
        base_delay = random.randint(self.min_delay, self.max_delay)
        logging.info(f"Safety delay: {base_delay} seconds")
        
        for i in range(base_delay):
            await asyncio.sleep(1)
            if random.random() < 0.1:
                await asyncio.sleep(random.uniform(0.5, 2.0))

    async def check_activity_limits(self):
        """Check if we've hit any activity limits"""
        now = datetime.now()
        
        if (now - self.last_activity).seconds >= 3600:
            self.adds_this_hour = 0
            self.last_activity = now
        
        if self.adds_today >= self.daily_add_limit:
            logging.warning(f"Daily limit reached ({self.daily_add_limit})")
            return False
            
        if self.adds_this_hour >= self.hourly_add_limit:
            logging.warning(f"Hourly limit reached ({self.hourly_add_limit})")
            wait_time = 3600 - (now - self.last_activity).seconds
            logging.info(f"Waiting {wait_time} seconds for hourly reset")
            await asyncio.sleep(wait_time)
            self.adds_this_hour = 0
            self.last_activity = datetime.now()
            
        return True

    async def handle_authentication(self):
        """Handle automatic authentication with session management"""
        try:
            # Check if we have a valid session string
            if self.session_string and len(self.session_string) > 10:
                await self.client.start()
                me = await self.client.get_me()
                logging.info(f"✅ Authenticated with session as {me.username or me.id}")
                return True
            else:
                # First-time setup - this will require manual intervention
                logging.info("🔑 No valid session string found. Starting first-time setup...")
                await self.client.start(phone=self.phone)
                me = await self.client.get_me()
                
                # Save session string for future use
                session_string = self.client.session.save()
                logging.info(f"🆕 NEW SESSION STRING: {session_string}")
                logging.info("💾 SAVE THIS SESSION_STRING IN YOUR RENDER ENVIRONMENT VARIABLES!")
                
                # Save to file as backup
                with open('session_string.txt', 'w') as f:
                    f.write(session_string)
                    
                logging.info("✅ First-time setup completed successfully!")
                return True
                
        except SessionPasswordNeededError:
            logging.error("🔒 2FA password required - cannot automate this.")
            return False
        except Exception as e:
            logging.error(f"❌ Authentication failed: {e}")
            return False

    async def smart_member_addition(self, target_group, user_list):
        """Smart member addition with enhanced safety"""
        if not await self.check_activity_limits():
            return 0
            
        added_count = 0
        try:
            target_entity = await self.client.get_entity(target_group)
        except Exception as e:
            logging.error(f"❌ Could not find target group {target_group}: {e}")
            return 0
        
        for user in user_list[:self.session_add_limit]:
            if not await self.check_activity_limits():
                break
                
            try:
                user_entity = await self.client.get_entity(user['id'])
                await self.client(functions.channels.InviteToChannelRequest(
                    channel=target_entity,
                    users=[user_entity]
                ))
                
                self.adds_today += 1
                self.adds_this_hour += 1
                added_count += 1
                
                logging.info(f"✅ Added user {added_count}: {user.get('username', user['id'])}")
                
                await self.safe_operation_delay()
                
            except (FloodWaitError, PeerFloodError) as e:
                wait_time = getattr(e, 'seconds', 900)
                logging.warning(f"⏳ Flood wait: {wait_time} seconds")
                await asyncio.sleep(wait_time + 10)
                
            except (UserPrivacyRestrictedError, UserAlreadyParticipantError) as e:
                logging.info(f"⚠️ User cannot be added: {type(e).__name__}")
                
            except Exception as e:
                logging.error(f"❌ Unexpected error: {e}")
                await asyncio.sleep(30)

        await self.update_daily_stats()
        return added_count

    async def scrape_members_safe(self, channel_username):
        """Safely scrape channel members"""
        try:
            channel = await self.client.get_entity(channel_username)
            members = []
            offset = 0
            
            while len(members) < 100:
                participants = await self.client(functions.channels.GetParticipantsRequest(
                    channel=channel,
                    filter=types.ChannelParticipantsSearch(''),
                    offset=offset,
                    limit=100,
                    hash=0
                ))
                
                if not participants.users:
                    break
                    
                for user in participants.users:
                    if not user.bot and not user.deleted:
                        members.append({
                            'id': user.id,
                            'username': user.username,
                            'first_name': user.first_name,
                            'last_name': user.last_name
                        })
                
                offset += len(participants.users)
                logging.info(f"📊 Scraped {len(members)} members so far...")
                await asyncio.sleep(10)
                
            logging.info(f"✅ Finished scraping {len(members)} members from {channel_username}")
            return members
            
        except Exception as e:
            logging.error(f"❌ Scraping failed: {e}")
            return []

    async def continuous_operation(self):
        """Main continuous operation loop"""
        logging.info("🚀 Starting continuous operation mode...")
        
        # CONFIGURE THESE FOR YOUR NEEDS:
        SCRAPE_TARGETS = ["@telegram", "@pythontelegram"]  # Change to your source channels
        ADD_TARGETS = ["@yourgroup"]  # Change to your target group
        
        while True:
            try:
                # Check authentication
                if not await self.client.is_user_authorized():
                    logging.info("🔄 Re-authenticating...")
                    if not await self.handle_authentication():
                        logging.error("❌ Authentication failed. Waiting 1 hour before retry.")
                        await asyncio.sleep(3600)
                        continue
                
                # Check daily limits
                if self.adds_today >= self.daily_add_limit:
                    logging.info("📊 Daily limit reached. Waiting until tomorrow.")
                    await asyncio.sleep(86400)
                    self.adds_today = 0
                    await self.update_daily_stats()
                    continue
                
                # Main operation cycle
                for scrape_target in SCRAPE_TARGETS:
                    if self.adds_today >= self.daily_add_limit:
                        break
                        
                    logging.info(f"🔍 Scraping from: {scrape_target}")
                    members = await self.scrape_members_safe(scrape_target)
                    
                    if not members:
                        continue
                        
                    for add_target in ADD_TARGETS:
                        if self.adds_today >= self.daily_add_limit:
                            break
                            
                        logging.info(f"👥 Adding to: {add_target}")
                        added = await self.smart_member_addition(add_target, members)
                        logging.info(f"✅ Added {added} users to {add_target}")
                        
                        if added == 0:
                            logging.info("💤 No users added this cycle, taking break")
                            break
                
                # Long break between cycles
                long_break = random.randint(7200, 21600)  # 2-6 hours
                logging.info(f"💤 Cycle completed. Taking break for {long_break//3600} hours.")
                await asyncio.sleep(long_break)
                
            except Exception as e:
                logging.error(f"💥 Critical error: {e}")
                await asyncio.sleep(600)

async def main():
    logging.info("🤖 Telegram Auto Bot Starting...")
    bot = TelegramAutoBot()
    
    if not await bot.handle_authentication():
        logging.error("❌ Initial authentication failed. Exiting.")
        return
    
    logging.info("✅ Authentication successful! Starting continuous operation...")
    await bot.continuous_operation()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Bot stopped by user")
    except Exception as e:
        logging.error(f💥 Fatal error: {e}")
