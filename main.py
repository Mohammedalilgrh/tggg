import asyncio
import random
import time
import json
import os
from datetime import datetime
from telethon import TelegramClient, functions, types
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, PeerFloodError,
    UserNotMutualContactError, UserChannelsTooMuchError,
    ChatAdminRequiredError, UserAlreadyParticipantError
)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_bot.log'),
        logging.StreamHandler()
    ]
)

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TelegramScraper:
    def __init__(self):
        self.api_id = os.getenv("API_ID")
        self.api_hash = os.getenv("API_HASH")
        self.phone = os.getenv("PHONE_NUMBER")
        self.client = TelegramClient('session', self.api_id, self.api_hash)
        self.scraped_users = []
        self.added_users = set()
        self.privacy_failed = set()
        self.failed_users = set()
        self.already_participant = set()
        self.session_start = datetime.now()

        # Anti-ban settings
        self.min_delay = 35
        self.max_delay = 95
        self.session_limit = 500
        self.flood_wait_threshold = 1800

    async def start_client(self):
        try:
            await self.client.start(phone=self.phone)
            me = await self.client.get_me()
            logging.info(f"Logged in as {me.username or me.id}")
            return True
        except Exception as e:
            logging.error(f"Failed to start client: {e}")
            return False

    async def safe_delay(self, min_delay=None, max_delay=None):
        d1 = min_delay if min_delay else self.min_delay
        d2 = max_delay if max_delay else self.max_delay
        delay = random.randint(d1, d2)
        logging.info(f"Waiting {delay} seconds for safety...")
        await asyncio.sleep(delay)

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
                        await self.safe_delay(10, 25)
                    participants = await self.client(
                        functions.channels.GetParticipantsRequest(
                            channel=channel,
                            filter=types.ChannelParticipantsSearch(''),
                            offset=offset,
                            limit=limit,
                            hash=0
                        )
                    )
                    
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
                            'is_premium': getattr(user, 'premium', False),
                            'scraped_at': datetime.utcnow().isoformat()
                        }
                        
                        # Save to Supabase
                        try:
                            supabase.table('scraped_users').insert(member_data).execute()
                        except Exception as e:
                            logging.error(f"Error saving to Supabase: {e}")
                        
                        members.append(member_data)
                    
                    offset += len(participants.users)
                    logging.info(f"Scraped {len(members)} members so far...")
                    
                    if len(participants.users) < limit:
                        break
                except FloodWaitError as e:
                    logging.warning(f"Flood wait! Sleeping for {e.seconds} seconds.")
                    await asyncio.sleep(e.seconds + 5)
                except Exception as e:
                    logging.error(f"Error scraping: {e}")
                    break
            
            self.scraped_users = members
            logging.info(f"Scraped {len(members)} users from {channel_username}.")
            return members
        except Exception as e:
            logging.error(f"Failed to scrape {channel_username}: {e}")
            return []

    async def add_member_to_group(self, target_group, user_data):
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
            
            res = await self.client(
                functions.channels.InviteToChannelRequest(
                    channel=target_group,
                    users=[user_to_add]
                )
            )
            
            # Update Supabase record
            try:
                supabase.table('scraped_users').update({
                    'added_to_group': target_group,
                    'added_at': datetime.utcnow().isoformat()
                }).eq('id', user_data['id']).execute()
            except Exception as e:
                logging.error(f"Error updating Supabase: {e}")
            
            self.added_users.add(user_key)
            return "added"
        except UserAlreadyParticipantError:
            self.already_participant.add(user_key)
            return "already"
        except UserPrivacyRestrictedError:
            self.privacy_failed.add(user_key)
            return "privacy"
        except (PeerFloodError, FloodWaitError) as e:
            if hasattr(e, "seconds") and e.seconds > self.flood_wait_threshold:
                logging.error(f"Flood wait over {self.flood_wait_threshold // 60} min, aborting for safety.")
                raise e
            logging.warning(f"Flood wait detected: sleeping for {getattr(e, 'seconds', 180)} seconds")
            await asyncio.sleep(getattr(e, "seconds", 180) + 10)
            return "flood"
        except Exception as e:
            logging.error(f"Failed to add user {user_key}: {e}")
            self.failed_users.add(user_key)
            return "fail"

    async def bulk_add_members(self, target_group, how_many=None):
        raw_target = target_group
        try:
            target_group = await self.client.get_entity(target_group)
        except Exception as e:
            logging.error(f"Could not resolve target group {raw_target}: {e}")
            return
        
        user_list = [u for u in self.scraped_users if (u.get('username') or str(u.get('id'))) not in self.added_users]
        random.shuffle(user_list)
        
        if not user_list:
            logging.info("No users to add. Did you scrape users?")
            return
        
        if not how_many:
            how_many = len(user_list)
        
        added = 0
        privacy = 0
        already = 0
        skipped = 0
        failed = 0
        flood = 0
        
        for user in user_list:
            if added >= how_many:
                break
            try:
                status = await self.add_member_to_group(target_group, user)
                if status == "added":
                    added += 1
                    logging.info(f"Added: @{user.get('username', user.get('id'))}")
                elif status == "privacy":
                    privacy += 1
                    logging.info(f"Privacy block: @{user.get('username', user.get('id'))}")
                elif status == "already":
                    already += 1
                elif status == "skipped":
                    skipped += 1
                elif status == "flood":
                    flood += 1
                else:
                    failed += 1
                await self.safe_delay()
            except (PeerFloodError, FloodWaitError) as e:
                logging.error("Flood wait or ban risk! Aborting.")
                break
            except KeyboardInterrupt:
                logging.info("Aborted by user.")
                break
            except Exception as e:
                logging.error(f"Error in bulk add: {e}")
                failed += 1
        
        logging.info(f"Bulk Add Finished: {added} added | {privacy} privacy blocked | {already} already in group | {failed} failed | {flood} flood-wait/peerflood | {skipped} skipped.")

# Initialize scraper
scraper = TelegramScraper()

@app.on_event("startup")
async def startup_event():
    await scraper.start_client()

@app.post("/api/scrape")
async def start_scraping(channel: str, count: int = 0):
    try:
        members = await scraper.scrape_channel_members(channel)
        return {"status": "success", "scraped_count": len(members)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/add")
async def start_adding(target: str, count: int = 0):
    try:
        await scraper.bulk_add_members(target, count)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/control")
async def control_operation(action: str):
    if action == "pause":
        # Implement pause logic if needed
        return {"status": "paused"}
    elif action == "resume":
        # Implement resume logic if needed
        return {"status": "resumed"}
    elif action == "stop":
        # Implement stop logic if needed
        return {"status": "stopped"}
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

@app.get("/api/stats")
async def get_stats():
    return {
        "scraped": len(scraper.scraped_users),
        "added": len(scraper.added_users),
        "privacy_blocked": len(scraper.privacy_failed),
        "failed": len(scraper.failed_users)
    }

@app.get("/api/data/download")
async def download_scraped_data():
    try:
        # Fetch all scraped users from Supabase
        data, count = supabase.table('scraped_users').select('*').execute()
        return {"users": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))