import os
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
import logging

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn
from telethon import TelegramClient, functions, types
from telethon.errors import SessionPasswordNeededError, FloodWaitError
import aiofiles
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
SESSION_STRING = os.getenv('SESSION_STRING', 'sessions')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# Validate required environment variables
if not all([API_ID, API_HASH, SUPABASE_URL, SUPABASE_KEY]):
    missing = []
    if not API_ID: missing.append('API_ID')
    if not API_HASH: missing.append('API_HASH')
    if not SUPABASE_URL: missing.append('SUPABASE_URL')
    if not SUPABASE_KEY: missing.append('SUPABASE_KEY')
    raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

# Initialize FastAPI app
app = FastAPI(title="Telegram User Scraper", version="1.0.0")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize Telegram client
client = TelegramClient(SESSION_STRING, int(API_ID), API_HASH)

# Pydantic models
class UserResponse(BaseModel):
    id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    is_premium: Optional[bool]
    scraped_at: datetime
    added_to_group: Optional[str]
    added_at: Optional[datetime]

class ScrapeRequest(BaseModel):
    group_username: str
    limit: Optional[int] = 100

class ScrapeResponse(BaseModel):
    status: str
    message: str
    users_scraped: int
    task_id: Optional[str] = None

class AddUserRequest(BaseModel):
    user_id: int
    group_username: str

class AddUserResponse(BaseModel):
    status: str
    message: str

# Global variables for background tasks
scraping_tasks: Dict[str, asyncio.Task] = {}

@app.on_event("startup")
async def startup_event():
    """Connect Telegram client on startup"""
    try:
        await client.start(phone=lambda: PHONE_NUMBER if PHONE_NUMBER else '')
        logger.info("Telegram client connected successfully")
        
        # Test Supabase connection
        try:
            result = supabase.table('scraped_users').select('count', count='exact').limit(1).execute()
            logger.info("Supabase connection established successfully")
        except Exception as e:
            logger.error(f"Supabase connection failed: {e}")
            
    except Exception as e:
        logger.error(f"Failed to connect Telegram client: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Disconnect Telegram client on shutdown"""
    if client.is_connected():
        await client.disconnect()
        logger.info("Telegram client disconnected")

async def scrape_group_members_task(task_id: str, group_username: str, limit: int):
    """Background task to scrape group members"""
    try:
        logger.info(f"Starting to scrape group: {group_username}")
        
        # Get group entity
        try:
            group_entity = await client.get_entity(group_username)
        except Exception as e:
            logger.error(f"Failed to get group entity: {e}")
            return
        
        # Get all participants
        participants = await client.get_participants(group_entity, limit=limit)
        logger.info(f"Found {len(participants)} participants in group")
        
        scraped_count = 0
        for participant in participants:
            try:
                # Prepare user data
                user_data = {
                    'id': participant.id,
                    'username': participant.username,
                    'first_name': participant.first_name,
                    'last_name': participant.last_name,
                    'phone': participant.phone,
                    'is_premium': participant.premium if hasattr(participant, 'premium') else False,
                    'scraped_at': datetime.now().isoformat(),
                    'added_to_group': None,
                    'added_at': None
                }
                
                # Insert or update user in database
                try:
                    result = supabase.table('scraped_users').upsert(user_data).execute()
                    scraped_count += 1
                    logger.debug(f"Scraped user: {participant.id}")
                except Exception as e:
                    logger.error(f"Failed to insert user {participant.id}: {e}")
                    
            except Exception as e:
                logger.error(f"Error processing participant: {e}")
                continue
        
        logger.info(f"Successfully scraped {scraped_count} users from {group_username}")
        
    except FloodWaitError as e:
        logger.error(f"Flood wait error: {e}")
    except Exception as e:
        logger.error(f"Error in scraping task: {e}")
    finally:
        # Remove task from tracking when completed
        if task_id in scraping_tasks:
            del scraping_tasks[task_id]

@app.post("/scrape-group", response_model=ScrapeResponse)
async def scrape_group_members(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """Start scraping members from a group"""
    try:
        task_id = f"scrape_{request.group_username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create background task
        task = asyncio.create_task(
            scrape_group_members_task(task_id, request.group_username, request.limit)
        )
        scraping_tasks[task_id] = task
        
        return ScrapeResponse(
            status="success",
            message=f"Started scraping group {request.group_username}",
            users_scraped=0,
            task_id=task_id
        )
        
    except Exception as e:
        logger.error(f"Error starting scrape task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/add-user-to-group", response_model=AddUserResponse)
async def add_user_to_group(request: AddUserRequest):
    """Add a scraped user to a group"""
    try:
        # Check if user exists in database
        user_result = supabase.table('scraped_users').select('*').eq('id', request.user_id).execute()
        
        if not user_result.data:
            raise HTTPException(status_code=404, detail="User not found in database")
        
        # Get group entity
        try:
            group_entity = await client.get_entity(request.group_username)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Group not found: {e}")
        
        # Add user to group
        try:
            await client(functions.channels.InviteToChannelRequest(
                channel=group_entity,
                users=[request.user_id]
            ))
            
            # Update database
            update_data = {
                'added_to_group': request.group_username,
                'added_at': datetime.now().isoformat()
            }
            supabase.table('scraped_users').update(update_data).eq('id', request.user_id).execute()
            
            return AddUserResponse(
                status="success",
                message=f"User {request.user_id} added to {request.group_username}"
            )
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to add user to group: {e}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding user to group: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users", response_model=List[UserResponse])
async def get_scraped_users(limit: int = 100, offset: int = 0):
    """Get all scraped users with pagination"""
    try:
        result = supabase.table('scraped_users')\
            .select('*')\
            .order('scraped_at', desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        
        return result.data
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int):
    """Get a specific user by ID"""
    try:
        result = supabase.table('scraped_users').select('*').eq('id', user_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Check status of a background task"""
    if task_id in scraping_tasks:
        task = scraping_tasks[task_id]
        if task.done():
            if task.exception():
                return {"status": "error", "message": str(task.exception())}
            else:
                return {"status": "completed"}
        else:
            return {"status": "running"}
    else:
        raise HTTPException(status_code=404, detail="Task not found")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    telegram_status = "connected" if client.is_connected() else "disconnected"
    
    try:
        supabase.table('scraped_users').select('count', count='exact').limit(1).execute()
        supabase_status = "connected"
    except Exception:
        supabase_status = "disconnected"
    
    return {
        "status": "healthy",
        "telegram": telegram_status,
        "supabase": supabase_status,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Telegram User Scraper API",
        "version": "1.0.0",
        "endpoints": {
            "scrape_group": "POST /scrape-group",
            "add_user": "POST /add-user-to-group", 
            "get_users": "GET /users",
            "get_user": "GET /users/{user_id}",
            "health": "GET /health"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
