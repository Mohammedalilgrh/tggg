import asyncio
import json
import os
from datetime import datetime
from telethon import TelegramClient, functions, types
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# إعداد Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TelegramScraper:
    def __init__(self):
        self.api_id = os.getenv("API_ID")
        self.api_hash = os.getenv("API_HASH")
        self.client = TelegramClient('session', self.api_id, self.api_hash)  # بدون رقم الهاتف
        self.scraped_users = []

    async def start_client(self):
        try:
            await self.client.start()  # استخدم الجلسة المحفوظة
            me = await self.client.get_me()
            print(f"Logged in as {me.username or me.id}")
            return True
        except Exception as e:
            print(f"Failed to start client: {e}")
            return False

    async def scrape_channel_members(self, channel_username):
        try:
            channel = await self.client.get_entity(channel_username)
            members = []
            offset = 0
            limit = 100
            
            while True:
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
                        'scraped_at': datetime.utcnow().isoformat()
                    }
                    
                    # حفظ البيانات في Supabase
                    try:
                        supabase.table('scraped_users').insert(member_data).execute()
                    except:
                        pass
                    
                    members.append(member_data)
                
                offset += len(participants.users)
                
                if len(participants.users) < limit:
                    break
                
                await asyncio.sleep(10)
            
            self.scraped_users = members
            return members
        except Exception as e:
            print(f"Error scraping: {e}")
            return []

# إنشاء scraper
scraper = TelegramScraper()

@app.on_event("startup")
async def startup_event():
    await scraper.start_client()

@app.post("/api/scrape")
async def start_scraping(channel: str):
    members = await scraper.scrape_channel_members(channel)
    return {"status": "success", "scraped_count": len(members)}

@app.get("/api/data/download")
async def download_scraped_data():
    try:
        data, count = supabase.table('scraped_users').select('*').execute()
        return {"users": data[1]}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
