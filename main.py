import asyncio
import random
import time
import json
import os
from datetime import datetime, timedelta
from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, PeerFloodError,
    UserNotMutualContactError, UserChannelsTooMuchError,
    ChatAdminRequiredError, UserAlreadyParticipantError, SessionPasswordNeededError
)
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

class TelegramScraper:
    def __init__(self):
        # Get from environment variables
        self.api_id = os.getenv('API_ID', '21706160')
        self.api_hash = os.getenv('API_HASH', '548b91f0e7cd2e44bbee05190620d9f4')
        self.phone = os.getenv('PHONE_NUMBER', '+96407762476460')
        self.session_string = os.getenv('SESSION_STRING', '')
        
        # Initialize client with session string
        if self.session_string:
            self.client = TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash)
        else:
            self.client = TelegramClient('session', self.api_id, self.api_hash)
            
        self.scraped_users = []
        self.added_users = set()
        self.privacy_failed = set()
        self.failed_users = set()
        self.already_participant = set()
        self.session_start = datetime.now()

        # Enhanced anti-ban settings
        self.min_delay = 45
        self.max_delay = 120
        self.daily_limit = 150
        self.hourly_limit = 20
        self.session_limit = 30
        self.flood_wait_threshold = 900

        # Activity tracking
        self.adds_today = 0
        self.adds_this_hour = 0
        self.last_activity = datetime.now()

    async def start_client(self):
        try:
            if self.session_string:
                await self.client.start()
                me = await self.client.get_me()
                logging.info(f"Logged in with session as {me.username or me.id}")
            else:
                await self.client.start(phone=self.phone)
                me = await self.client.get_me()
                logging.info(f"Logged in as {me.username or me.id}")
                
                # Save session string for future use
                session_string = self.client.session.save()
                logging.info(f"NEW SESSION STRING: {session_string}")
                logging.info("SAVE THIS TO YOUR RENDER ENVIRONMENT VARIABLES!")
            return True
        except SessionPasswordNeededError:
            logging.error("2FA password required - cannot automate this.")
            return False
        except Exception as e:
            logging.error(f"Failed to start client: {e}")
            return False

    async def safe_delay(self, min_delay=None, max_delay=None):
        d1 = min_delay if min_delay else self.min_delay
        d2 = max_delay if max_delay else self.max_delay
        delay = random.randint(d1, d2)
        logging.info(f"Waiting {delay} seconds for safety...")
        
        # Add micro-delays to simulate human behavior
        for i in range(delay):
            await asyncio.sleep(1)
            if random.random() < 0.1:  # 10% chance of micro-delay
                await asyncio.sleep(random.uniform(0.5, 2.0))

    async def check_rate_limits(self):
        """Check if we've hit any rate limits"""
        now = datetime.now()
        
        # Reset hourly counter if new hour
        if (now - self.last_activity).seconds >= 3600:
            self.adds_this_hour = 0
            self.last_activity = now
        
        # Check daily limit
        if self.adds_today >= self.daily_limit:
            logging.warning(f"Daily limit reached ({self.daily_limit}). Stopping for today.")
            return False
            
        # Check hourly limit
        if self.adds_this_hour >= self.hourly_limit:
            logging.warning(f"Hourly limit reached ({self.hourly_limit}). Waiting...")
            wait_time = 3600 - (now - self.last_activity).seconds
            await asyncio.sleep(wait_time)
            self.adds_this_hour = 0
            self.last_activity = datetime.now()
            
        return True

    async def scrape_channel_members(self, channel_username):
        try:
            logging.info(f"Starting to scrape: {channel_username}")
            channel = await self.client.get_entity(channel_username)
            members = []
            offset = 0
            limit = 100
            
            while True:
                try:
                    if offset > 0:
                        await self.safe_delay(15, 30)
                    
                    participants = await self.client(functions.channels.GetParticipantsRequest(
                        channel=channel,
                        filter=types.ChannelParticipantsSearch(''),
                        offset=offset,
                        limit=limit,
                        hash=0
                    ))
                    
                    if not participants.users:
                        break
                    
                    for user in participants.users:
                        if user.bot or user.deleted:
                            continue
                        member_data = {
                            'id': user.id,
                            'username': user.username,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'phone': user.phone,
                            'is_premium': getattr(user, 'premium', False)
                        }
                        members.append(member_data)
                    
                    offset += len(participants.users)
                    logging.info(f"Scraped {len(members)} members so far...")
                    
                    if len(participants.users) < limit:
                        break
                        
                except FloodWaitError as e:
                    logging.warning(f"Flood wait! Sleeping for {e.seconds} seconds.")
                    await asyncio.sleep(e.seconds + 10)
                except Exception as e:
                    logging.error(f"Error scraping: {e}")
                    break
            
            self.scraped_users = members
            logging.info(f"Scraped {len(members)} users from {channel_username}")
            return members
            
        except Exception as e:
            logging.error(f"Failed to scrape {channel_username}: {e}")
            return []

    async def add_member_to_group(self, target_group, user_data):
        if not await self.check_rate_limits():
            return "daily_limit_reached"
            
        user_key = user_data.get('username') or str(user_data.get('id'))
        if user_key in self.added_users or user_key in self.privacy_failed or user_key in self.already_participant:
            return "skipped"
            
        try:
            user_to_add = None
            if user_data.get('username'):
                try:
                    user_to_add = await self.client.get_entity(user_data['username'])
                except Exception:
                    pass
                    
            if not user_to_add and user_data.get('id'):
                try:
                    user_to_add = await self.client.get_entity(user_data['id'])
                except Exception:
                    pass
                    
            if not user_to_add:
                self.failed_users.add(user_key)
                return "fail"
                
            # Additional random delay before actual add
            await asyncio.sleep(random.uniform(2, 5))
                
            await self.client(functions.channels.InviteToChannelRequest(
                channel=target_group,
                users=[user_to_add]
            ))
            
            self.added_users.add(user_key)
            self.adds_today += 1
            self.adds_this_hour += 1
            self.last_activity = datetime.now()
            
            return "added"
            
        except UserAlreadyParticipantError:
            self.already_participant.add(user_key)
            return "already"
        except UserPrivacyRestrictedError:
            self.privacy_failed.add(user_key)
            return "privacy"
        except (PeerFloodError, FloodWaitError) as e:
            wait_time = getattr(e, "seconds", 180)
            if wait_time > self.flood_wait_threshold:
                logging.error(f"Flood wait over {self.flood_wait_threshold // 60} min, aborting.")
                raise e
            logging.warning(f"Flood wait detected: sleeping for {wait_time} seconds")
            await asyncio.sleep(wait_time + 10)
            return "flood"
        except Exception as e:
            logging.error(f"Failed to add user {user_key}: {e}")
            self.failed_users.add(user_key)
            return "fail"

    async def automated_workflow(self):
        """Automated workflow that runs continuously"""
        logging.info("Starting automated workflow...")
        
        # Configure your target channels and groups here
        SOURCE_CHANNELS = ["@channel1", "@channel2"]  # Replace with your source channels
        TARGET_GROUPS = ["@yourgroup1"]  # Replace with your target groups
        
        while True:
            try:
                # Check if we need to restart authentication
                if not await self.client.is_user_authorized():
                    logging.info("Re-authenticating...")
                    if not await self.start_client():
                        logging.error("Authentication failed. Waiting 1 hour before retry.")
                        await asyncio.sleep(3600)
                        continue
                
                # Check daily limits
                if self.adds_today >= self.daily_limit:
                    logging.info(f"Daily limit reached ({self.adds_today}/{self.daily_limit}). Waiting until tomorrow.")
                    await asyncio.sleep(86400)  # Wait 24 hours
                    self.adds_today = 0
                    continue
                
                # Main automation cycle
                for source_channel in SOURCE_CHANNELS:
                    if self.adds_today >= self.daily_limit:
                        break
                        
                    logging.info(f"Scraping from: {source_channel}")
                    members = await self.scrape_channel_members(source_channel)
                    
                    if not members:
                        continue
                        
                    for target_group in TARGET_GROUPS:
                        if self.adds_today >= self.daily_limit:
                            break
                            
                        logging.info(f"Adding members to: {target_group}")
                        
                        # Filter users and shuffle
                        user_list = [u for u in members if (u.get('username') or str(u.get('id'))) not in self.added_users]
                        random.shuffle(user_list)
                        
                        if not user_list:
                            logging.info("No new users to add")
                            continue
                            
                        # Add users with limits
                        added = 0
                        for user in user_list[:self.session_limit]:
                            if self.adds_today >= self.daily_limit:
                                break
                                
                            status = await self.add_member_to_group(target_group, user)
                            if status == "added":
                                added += 1
                                logging.info(f"Added user {added}: @{user.get('username', user.get('id'))}")
                            elif status == "daily_limit_reached":
                                break
                                
                            await self.safe_delay()
                        
                        logging.info(f"Added {added} users to {target_group} this session")
                
                # Long break between cycles (2-4 hours)
                long_break = random.randint(7200, 14400)
                logging.info(f"Cycle completed. Taking break for {long_break//3600} hours.")
                await asyncio.sleep(long_break)
                
            except Exception as e:
                logging.error(f"Error in automated workflow: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retrying

    async def run(self):
        if not await self.start_client():
            return
        
        # Start automated workflow instead of interactive menu
        await self.automated_workflow()

if __name__ == "__main__":
    scraper = TelegramScraper()
    
    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
