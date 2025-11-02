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
        self.session_string = os.getenv('SESSION_STRING', '')
        
        # Supabase configuration
        supabase_url = os.getenv('SUPABASE_URL', 'https://apseoggiwlcdwzihfthz.supabase.co')
        supabase_key = os.getenv('SUPABASE_KEY', 'your_supabase_key_here')
        self.supabase = create_client(supabase_url, supabase_key)
        
        # Enhanced anti-ban settings [citation:2][citation:6]
        self.min_delay = 60  # Increased to 60-180 seconds
        self.max_delay = 180
        self.daily_add_limit = 150  # Conservative daily limit
        self.hourly_add_limit = 20  # Per-hour limit
        self.session_add_limit = 30  # Per-session limit
        
        # Activity tracking
        self.adds_today = 0
        self.adds_this_hour = 0
        self.last_activity = datetime.now()
        self.session_start = datetime.now()
        
        # Initialize client
        if self.session_string:
            self.client = TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash)
        else:
            self.client = TelegramClient('session', self.api_id, self.api_hash)
            
        # Load previous stats
        self.load_daily_stats()

    def load_daily_stats(self):
        """Load daily statistics from Supabase"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            result = self.supabase.table('daily_stats').select('*').eq('date', today).execute()
            if result.data:
                self.adds_today = result.data[0].get('adds_count', 0)
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
        except Exception as e:
            logging.error(f"Error updating stats: {e}")

    async def safe_operation_delay(self):
        """Enhanced safety delay with random patterns [citation:2][citation:6]"""
        base_delay = random.randint(self.min_delay, self.max_delay)
        
        # Add micro-delays to simulate human behavior
        for i in range(base_delay):
            await asyncio.sleep(1)
            # Random micro-pauses
            if random.random() < 0.1:  # 10% chance of micro-delay
                await asyncio.sleep(random.uniform(0.5, 2.0))
                
        logging.info(f"Completed safety delay of {base_delay} seconds")

    async def check_activity_limits(self):
        """Check if we've hit any activity limits"""
        now = datetime.now()
        
        # Reset hourly counter if new hour
        if (now - self.last_activity).seconds >= 3600:
            self.adds_this_hour = 0
            self.last_activity = now
        
        # Check daily limit
        if self.adds_today >= self.daily_add_limit:
            logging.warning(f"Daily limit reached ({self.daily_add_limit}). Stopping for today.")
            return False
            
        # Check hourly limit
        if self.adds_this_hour >= self.hourly_add_limit:
            logging.warning(f"Hourly limit reached ({self.hourly_add_limit}). Waiting...")
            wait_time = 3600 - (now - self.last_activity).seconds
            await asyncio.sleep(wait_time)
            self.adds_this_hour = 0
            self.last_activity = datetime.now()
            
        return True

    async def handle_authentication(self):
        """Handle automatic authentication with session management"""
        try:
            if self.session_string:
                await self.client.start()
                me = await self.client.get_me()
                logging.info(f"Authenticated with session as {me.username or me.id}")
                return True
            else:
                # First-time setup
                await self.client.start(phone=self.phone)
                me = await self.client.get_me()
                
                # Save session string for future use
                session_string = self.client.session.save()
                logging.info(f"NEW SESSION STRING: {session_string}")
                logging.info("SAVE THIS SESSION_STRING IN YOUR RENDER ENVIRONMENT VARIABLES!")
                
                with open('session_string.txt', 'w') as f:
                    f.write(session_string)
                    
                return True
                
        except SessionPasswordNeededError:
            logging.error("2FA password required - cannot automate this.")
            return False
        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            return False

    async def human_like_activity(self):
        """Simulate human-like activity patterns [citation:6]"""
        activities = [
            self.browse_random_channel,
            self.read_messages,
            self.random_delay_activity
        ]
        
        # Randomly perform human-like activities
        if random.random() < 0.3:  # 30% chance
            activity = random.choice(activities)
            await activity()

    async def browse_random_channel(self):
        """Simulate browsing behavior"""
        try:
            # Get some dialogs to simulate normal usage
            dialogs = await self.client.get_dialogs(limit=5)
            await asyncio.sleep(random.randint(10, 30))
        except Exception as e:
            logging.debug(f"Browse activity error: {e}")

    async def read_messages(self):
        """Simulate reading messages"""
        await asyncio.sleep(random.randint(5, 15))

    async def random_delay_activity(self):
        """Random delay between activities"""
        await asyncio.sleep(random.randint(5, 20))

    async def smart_member_addition(self, target_group, user_list):
        """Smart member addition with enhanced safety"""
        if not await self.check_activity_limits():
            return
            
        added_count = 0
        target_entity = await self.client.get_entity(target_group)
        
        for user in user_list[:self.session_add_limit]:
            if not await self.check_activity_limits():
                break
                
            try:
                # Simulate human-like behavior before action
                await self.human_like_activity()
                
                user_entity = await self.client.get_entity(user['id'])
                await self.client(functions.channels.InviteToChannelRequest(
                    channel=target_entity,
                    users=[user_entity]
                ))
                
                # Update counters
                self.adds_today += 1
                self.adds_this_hour += 1
                added_count += 1
                
                # Save to Supabase
                await self.save_successful_add(user, target_group)
                
                logging.info(f"Successfully added user {added_count}: {user.get('username', user['id'])}")
                
                # Enhanced safety delay
                await self.safe_operation_delay()
                
            except (FloodWaitError, PeerFloodError) as e:
                wait_time = getattr(e, 'seconds', 900)
                if wait_time > 1800:  # 30 minutes
                    logging.error(f"Long flood wait detected: {wait_time} seconds. Stopping.")
                    break
                logging.warning(f"Flood wait: {wait_time} seconds")
                await asyncio.sleep(wait_time + 10)
                
            except (UserPrivacyRestrictedError, UserAlreadyParticipantError) as e:
                logging.info(f"User cannot be added: {type(e).__name__}")
                await self.save_failed_add(user, target_group, str(e))
                
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                await self.save_failed_add(user, target_group, str(e))
                await asyncio.sleep(30)  # Longer delay on errors

        await self.update_daily_stats()
        return added_count

    async def save_successful_add(self, user, target_group):
        """Save successful additions to Supabase"""
        try:
            data = {
                'user_id': user['id'],
                'username': user.get('username'),
                'target_group': target_group,
                'added_at': datetime.now().isoformat(),
                'daily_count': self.adds_today
            }
            self.supabase.table('successful_adds').insert(data).execute()
        except Exception as e:
            logging.error(f"Error saving successful add: {e}")

    async def save_failed_add(self, user, target_group, error):
        """Save failed attempts to Supabase"""
        try:
            data = {
                'user_id': user['id'],
                'username': user.get('username'),
                'target_group': target_group,
                'error': error,
                'failed_at': datetime.now().isoformat()
            }
            self.supabase.table('failed_adds').insert(data).execute()
        except Exception as e:
            logging.error(f"Error saving failed add: {e}")

    async def continuous_operation(self):
        """Main continuous operation loop"""
        logging.info("Starting continuous operation mode...")
        
        # Pre-defined targets (configure these)
        SCRAPE_TARGETS = ["@channel1", "@channel2"]  # Add your source channels
        ADD_TARGETS = ["@yourgroup1", "@yourgroup2"]  # Add your target groups
        
        while True:
            try:
                # Check authentication
                if not await self.client.is_user_authorized():
                    logging.info("Re-authenticating...")
                    if not await self.handle_authentication():
                        logging.error("Authentication failed. Waiting before retry.")
                        await asyncio.sleep(3600)  # Wait 1 hour
                        continue
                
                # Check daily limits
                if self.adds_today >= self.daily_add_limit:
                    logging.info("Daily limit reached. Waiting until tomorrow.")
                    await asyncio.sleep(86400)  # Wait 24 hours
                    self.adds_today = 0
                    await self.update_daily_stats()
                    continue
                
                # Main operation cycle
                for scrape_target in SCRAPE_TARGETS:
                    if self.adds_today >= self.daily_add_limit:
                        break
                        
                    # Scrape members
                    members = await self.scrape_members_safe(scrape_target)
                    
                    for add_target in ADD_TARGETS:
                        if self.adds_today >= self.daily_add_limit:
                            break
                            
                        # Add members with safety limits
                        added = await self.smart_member_addition(add_target, members)
                        if added == 0:  # If no adds, possibly limited
                            logging.info("No users added this cycle, taking longer break")
                            break
                
                # Long break between major cycles (2-6 hours)
                long_break = random.randint(7200, 21600)  # 2-6 hours
                logging.info(f"Cycle completed. Taking long break for {long_break//3600} hours.")
                await asyncio.sleep(long_break)
                
            except Exception as e:
                logging.error(f"Critical error in continuous operation: {e}")
                await asyncio.sleep(600)  # Wait 10 minutes before retry

    async def scrape_members_safe(self, channel_username):
        """Safely scrape channel members"""
        try:
            channel = await self.client.get_entity(channel_username)
            members = []
            offset = 0
            
            while len(members) < 100:  # Limit scrape size
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
                await asyncio.sleep(10)  # Delay between batches
                
            return members
            
        except Exception as e:
            logging.error(f"Scraping failed: {e}")
            return []

async def main():
    bot = TelegramAutoBot()
    
    # Try to authenticate
    if not await bot.handle_authentication():
        logging.error("Initial authentication failed. Exiting.")
        return
    
    # Start continuous operation
    await bot.continuous_operation()

if __name__ == "__main__":
    asyncio.run(main())
