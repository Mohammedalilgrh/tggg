import os
import asyncio
import json
import time
import random
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from telethon import TelegramClient, functions, types
from telethon.errors import (
    FloodWaitError, UserNotParticipantError, ChannelPrivateError,
    UserPrivacyRestrictedError, ChatAdminRequiredError, PeerFloodError
)
from supabase import create_client, Client
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = "21706160"
API_HASH = "548b91f0e7cd2e44bbee05190620d9f4"
SESSION_STRING = "session"
PHONE_NUMBER = "+96407762476460"
SUPABASE_URL = "https://apseoggiwlcdwzihfthz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFwc2VvZ2dpd2xjZHd6aWhmdGh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5ODk2NzMsImV4cCI6MjA3NzU2NTY3M30.ZD47Gvm1cFc-oE2hJyoStWHuCvdXFlrxdrgBPucfW0Q"

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Global variables for task management
active_tasks = {}
task_status = {}
scraped_users_queue = asyncio.Queue()
MAX_CONCURRENT_ADDITIONS = 2  # Limit concurrent additions to avoid bans

# Anti-ban configuration
ANTI_BAN_CONFIG = {
    'delay_between_adds': random.uniform(30, 60),  # 30-60 seconds between adds
    'max_daily_adds': 50,  # Maximum adds per day
    'chunk_size': 10,  # Process users in chunks
    'random_delay': True,
    'auto_pause_hours': [2, 3, 4],  # Auto-pause during night hours (2AM-5AM)
}

class ScrapeConfig(BaseModel):
    source_group: str
    limit: int = 100
    task_id: Optional[str] = None

class AddConfig(BaseModel):
    target_group: str
    users_per_hour: int = 20
    task_id: Optional[str] = None

class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    total: int
    message: str
    type: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Telegram Client...")
    global client
    client = TelegramClient(SESSION_STRING, int(API_ID), API_HASH)
    
    try:
        await client.start(phone=PHONE_NUMBER)
        if await client.is_user_authorized():
            me = await client.get_me()
            logger.info(f"Connected as {me.first_name} (@{me.username})")
        else:
            logger.error("Not authorized! Please check your session.")
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
    
    yield
    
    # Shutdown
    if client.is_connected():
        await client.disconnect()
        logger.info("Telegram client disconnected")

app = FastAPI(title="Telegram Group Manager", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Create necessary directories
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# HTML Templates
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Group Manager</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #0f0f0f; color: white; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { text-align: center; margin-bottom: 30px; }
        .dashboard { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }
        .card { background: #1a1a1a; padding: 20px; border-radius: 10px; border: 1px solid #333; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }
        .stat-card { background: #2a2a2a; padding: 15px; border-radius: 8px; text-align: center; }
        .controls { display: flex; gap: 10px; margin: 10px 0; }
        button { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }
        .btn-start { background: #00c853; color: white; }
        .btn-pause { background: #ff9800; color: white; }
        .btn-stop { background: #f44336; color: white; }
        .btn-resume { background: #2196f3; color: white; }
        .form-group { margin: 15px 0; }
        label { display: block; margin-bottom: 5px; color: #ccc; }
        input, select { width: 100%; padding: 10px; background: #2a2a2a; border: 1px solid #444; border-radius: 5px; color: white; }
        .task-list { margin-top: 20px; }
        .task-item { background: #2a2a2a; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #2196f3; }
        .progress-bar { width: 100%; height: 10px; background: #333; border-radius: 5px; margin: 10px 0; }
        .progress-fill { height: 100%; background: #2196f3; border-radius: 5px; transition: width 0.3s; }
        .live-feed { max-height: 300px; overflow-y: auto; background: #1a1a1a; padding: 15px; border-radius: 8px; }
        .log-entry { padding: 5px 0; border-bottom: 1px solid #333; font-family: monospace; font-size: 12px; }
        .status-running { color: #00c853; }
        .status-paused { color: #ff9800; }
        .status-stopped { color: #f44336; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Telegram Group Manager</h1>
            <p>Automated Member Scraping & Adding with Anti-Ban Protection</p>
        </div>

        <div class="stats">
            <div class="stat-card">
                <h3>📊 Total Users</h3>
                <p id="total-users">0</p>
            </div>
            <div class="stat-card">
                <h3>✅ Added Today</h3>
                <p id="added-today">0</p>
            </div>
            <div class="stat-card">
                <h3>⚡ Active Tasks</h3>
                <p id="active-tasks">0</p>
            </div>
            <div class="stat-card">
                <h3>🛡️ Protection</h3>
                <p id="protection-status">Active</p>
            </div>
        </div>

        <div class="dashboard">
            <div class="card">
                <h2>🔍 Scrape Members</h2>
                <form id="scrapeForm" onsubmit="startScraping(event)">
                    <div class="form-group">
                        <label for="sourceGroup">Source Group Username:</label>
                        <input type="text" id="sourceGroup" placeholder="@username" required>
                    </div>
                    <div class="form-group">
                        <label for="scrapeLimit">Number of Members to Scrape:</label>
                        <input type="number" id="scrapeLimit" value="100" min="1" max="10000">
                    </div>
                    <button type="submit" class="btn-start">Start Scraping</button>
                </form>
            </div>

            <div class="card">
                <h2>📤 Add Members</h2>
                <form id="addForm" onsubmit="startAdding(event)">
                    <div class="form-group">
                        <label for="targetGroup">Target Group Username:</label>
                        <input type="text" id="targetGroup" placeholder="@username" required>
                    </div>
                    <div class="form-group">
                        <label for="usersPerHour">Users Per Hour (Safe Limit):</label>
                        <select id="usersPerHour">
                            <option value="10">10 (Very Safe)</option>
                            <option value="20" selected>20 (Safe)</option>
                            <option value="30">30 (Moderate)</option>
                            <option value="50">50 (Aggressive)</option>
                        </select>
                    </div>
                    <button type="submit" class="btn-start">Start Adding</button>
                </form>
            </div>
        </div>

        <div class="card">
            <h2>📈 Active Tasks</h2>
            <div id="taskList" class="task-list">
                <!-- Tasks will be populated here -->
            </div>
        </div>

        <div class="card">
            <h2>📊 Live Activity Feed</h2>
            <div id="liveFeed" class="live-feed">
                <!-- Live logs will appear here -->
            </div>
        </div>

        <div class="card">
            <h2>🛡️ Anti-Ban Protection Status</h2>
            <div id="protectionInfo">
                <p>✅ Delays between actions: 30-60 seconds</p>
                <p>✅ Daily limit: 50 users</p>
                <p>✅ Automatic night pause: 2AM-5AM</p>
                <p>✅ Concurrent limit: 2 operations</p>
                <p>✅ Random delays enabled</p>
            </div>
        </div>
    </div>

    <script>
        let eventSource = null;
        
        function startScraping(event) {
            event.preventDefault();
            const sourceGroup = document.getElementById('sourceGroup').value;
            const limit = document.getElementById('scrapeLimit').value;
            
            fetch('/api/scrape', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({source_group: sourceGroup, limit: parseInt(limit)})
            }).then(r => r.json()).then(data => {
                addLog(`Started scraping: ${sourceGroup} (Limit: ${limit})`);
            });
        }
        
        function startAdding(event) {
            event.preventDefault();
            const targetGroup = document.getElementById('targetGroup').value;
            const usersPerHour = document.getElementById('usersPerHour').value;
            
            fetch('/api/add-members', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target_group: targetGroup, users_per_hour: parseInt(usersPerHour)})
            }).then(r => r.json()).then(data => {
                addLog(`Started adding to: ${targetGroup} (${usersPerHour}/hour)`);
            });
        }
        
        function controlTask(taskId, action) {
            fetch(`/api/tasks/${taskId}/${action}`, {method: 'POST'})
                .then(r => r.json())
                .then(data => addLog(`Task ${taskId}: ${action}`));
        }
        
        function addLog(message) {
            const feed = document.getElementById('liveFeed');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.innerHTML = `[${new Date().toLocaleTimeString()}] ${message}`;
            feed.appendChild(entry);
            feed.scrollTop = feed.scrollHeight;
        }
        
        function updateStats() {
            fetch('/api/stats').then(r => r.json()).then(stats => {
                document.getElementById('total-users').textContent = stats.total_users;
                document.getElementById('added-today').textContent = stats.added_today;
                document.getElementById('active-tasks').textContent = stats.active_tasks;
            });
            
            fetch('/api/tasks').then(r => r.json()).then(tasks => {
                const taskList = document.getElementById('taskList');
                taskList.innerHTML = '';
                
                tasks.forEach(task => {
                    const taskEl = document.createElement('div');
                    taskEl.className = 'task-item';
                    taskEl.innerHTML = `
                        <h4>${task.type.toUpperCase()}: ${task.task_id}</h4>
                        <p>Status: <span class="status-${task.status}">${task.status}</span></p>
                        <p>${task.message}</p>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${task.progress}%"></div>
                        </div>
                        <p>Progress: ${task.progress}% (${Math.round(task.progress * task.total / 100)}/${task.total})</p>
                        <div class="controls">
                            ${task.status === 'running' ? 
                                '<button class="btn-pause" onclick="controlTask(\'' + task.task_id + '\', \'pause\')">Pause</button>' : 
                                '<button class="btn-resume" onclick="controlTask(\'' + task.task_id + '\', \'resume\')">Resume</button>'
                            }
                            <button class="btn-stop" onclick="controlTask(\'' + task.task_id + '\', \'stop\')">Stop</button>
                        </div>
                    `;
                    taskList.appendChild(taskEl);
                });
            });
        }
        
        // Connect to SSE for live updates
        function connectSSE() {
            eventSource = new EventSource('/api/stream');
            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                if (data.type === 'log') {
                    addLog(data.message);
                } else if (data.type === 'stats_update') {
                    updateStats();
                }
            };
            eventSource.onerror = function() {
                setTimeout(connectSSE, 5000);
            };
        }
        
        // Initial load
        updateStats();
        connectSSE();
        setInterval(updateStats, 10000); // Update stats every 10 seconds
        
        // Add initial log
        addLog('System initialized and ready');
    </script>
</body>
</html>
"""

# Create static files and templates
def setup_directories():
    # Create HTML template
    with open("templates/index.html", "w") as f:
        f.write(HTML_TEMPLATE)
    
    # Create simple CSS file
    css_content = """
    body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: white; }
    .container { max-width: 1200px; margin: 0 auto; }
    """
    with open("static/style.css", "w") as f:
        f.write(css_content)

# Anti-ban safety functions
async def safe_delay(min_seconds=30, max_seconds=60):
    """Random delay to avoid detection"""
    delay = random.uniform(min_seconds, max_seconds)
    logger.info(f"🛡️ Safety delay: {delay:.1f} seconds")
    await asyncio.sleep(delay)

def is_night_hours():
    """Check if current time is in night pause hours"""
    current_hour = datetime.now().hour
    return current_hour in ANTI_BAN_CONFIG['auto_pause_hours']

async def check_daily_limit():
    """Check if daily add limit is reached"""
    today = datetime.now().date()
    result = supabase.table('scraped_users')\
        .select('*', count='exact')\
        .gte('added_at', today.isoformat())\
        .execute()
    return result.count or 0

# Core functions
async def scrape_members_task(task_id: str, source_group: str, limit: int):
    """Background task to scrape group members"""
    try:
        task_status[task_id] = {
            'status': 'running', 
            'progress': 0, 
            'total': limit, 
            'message': f'Scraping from {source_group}',
            'type': 'scrape'
        }
        
        logger.info(f"Starting to scrape {limit} members from {source_group}")
        
        # Get group entity
        try:
            entity = await client.get_entity(source_group)
            group_title = getattr(entity, 'title', source_group)
            task_status[task_id]['message'] = f'Scraping from: {group_title}'
        except Exception as e:
            task_status[task_id]['message'] = f'Error: Group not found - {e}'
            task_status[task_id]['status'] = 'error'
            return
        
        # Get participants
        participants = await client.get_participants(entity, limit=limit)
        total = len(participants)
        
        logger.info(f"Found {total} participants")
        
        scraped_count = 0
        for i, user in enumerate(participants):
            if task_status[task_id]['status'] == 'stopped':
                break
                
            while task_status[task_id]['status'] == 'paused':
                await asyncio.sleep(1)
                
            try:
                # Prepare user data
                user_data = {
                    'id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'phone': user.phone,
                    'is_premium': getattr(user, 'premium', False),
                    'scraped_at': datetime.now().isoformat(),
                    'added_to_group': None,
                    'added_at': None
                }
                
                # Save to database
                supabase.table('scraped_users').upsert(user_data).execute()
                scraped_count += 1
                
                # Update progress
                progress = int((i + 1) / total * 100)
                task_status[task_id]['progress'] = progress
                task_status[task_id]['message'] = f'Scraped {scraped_count}/{total} users'
                
                # Small delay to avoid flooding
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error processing user {user.id}: {e}")
                continue
        
        task_status[task_id]['status'] = 'completed'
        task_status[task_id]['message'] = f'Completed: {scraped_count} users scraped'
        logger.info(f"Scraping completed: {scraped_count} users")
        
    except Exception as e:
        logger.error(f"Scraping task error: {e}")
        task_status[task_id]['status'] = 'error'
        task_status[task_id]['message'] = f'Error: {str(e)}'

async def add_members_task(task_id: str, target_group: str, users_per_hour: int):
    """Background task to add members to target group"""
    try:
        task_status[task_id] = {
            'status': 'running', 
            'progress': 0, 
            'total': 100, 
            'message': f'Adding members to {target_group}',
            'type': 'add'
        }
        
        logger.info(f"Starting to add members to {target_group}")
        
        # Get target group entity
        try:
            target_entity = await client.get_entity(target_group)
            group_title = getattr(target_entity, 'title', target_group)
            task_status[task_id]['message'] = f'Adding to: {group_title}'
        except Exception as e:
            task_status[task_id]['message'] = f'Error: Target group not found - {e}'
            task_status[task_id]['status'] = 'error'
            return
        
        # Get users who haven't been added yet
        result = supabase.table('scraped_users')\
            .select('*')\
            .is_('added_to_group', 'null')\
            .execute()
        
        users_to_add = result.data
        total_users = len(users_to_add)
        
        if total_users == 0:
            task_status[task_id]['message'] = 'No users available to add'
            task_status[task_id]['status'] = 'completed'
            return
        
        logger.info(f"Found {total_users} users to add")
        
        added_count = 0
        failed_count = 0
        
        for i, user in enumerate(users_to_add):
            if task_status[task_id]['status'] == 'stopped':
                break
                
            while task_status[task_id]['status'] == 'paused':
                await asyncio.sleep(1)
            
            # Check daily limit
            daily_added = await check_daily_limit()
            if daily_added >= ANTI_BAN_CONFIG['max_daily_adds']:
                task_status[task_id]['message'] = f'Daily limit reached ({daily_added}/{ANTI_BAN_CONFIG["max_daily_adds"]})'
                await asyncio.sleep(3600)  # Wait 1 hour
                continue
            
            # Check night hours
            if is_night_hours():
                task_status[task_id]['message'] = 'Auto-paused during night hours'
                await asyncio.sleep(1800)  # Wait 30 minutes
                continue
            
            try:
                # Add user to group
                await client(functions.channels.InviteToChannelRequest(
                    channel=target_entity,
                    users=[user['id']]
                ))
                
                # Update database
                supabase.table('scraped_users').update({
                    'added_to_group': target_group,
                    'added_at': datetime.now().isoformat()
                }).eq('id', user['id']).execute()
                
                added_count += 1
                logger.info(f"✅ Added user {user['id']} to {target_group}")
                
                # Update progress
                progress = int((i + 1) / total_users * 100)
                task_status[task_id]['progress'] = progress
                task_status[task_id]['message'] = f'Added {added_count}/{total_users} users (Failed: {failed_count})'
                
                # Safety delay
                await safe_delay(30, 60)
                
            except FloodWaitError as e:
                logger.warning(f"⏳ Flood wait: {e.seconds} seconds")
                task_status[task_id]['message'] = f'Flood wait: {e.seconds}s'
                await asyncio.sleep(e.seconds + 10)
                
            except (UserPrivacyRestrictedError, UserNotParticipantError, ChannelPrivateError) as e:
                logger.warning(f"❌ Cannot add user {user['id']}: {e}")
                failed_count += 1
                continue
                
            except Exception as e:
                logger.error(f"Error adding user {user['id']}: {e}")
                failed_count += 1
                continue
        
        task_status[task_id]['status'] = 'completed'
        task_status[task_id]['message'] = f'Completed: {added_count} added, {failed_count} failed'
        logger.info(f"Adding completed: {added_count} users added to {target_group}")
        
    except Exception as e:
        logger.error(f"Adding task error: {e}")
        task_status[task_id]['status'] = 'error'
        task_status[task_id]['message'] = f'Error: {str(e)}'

# API Routes
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    setup_directories()
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/scrape")
async def start_scraping(config: ScrapeConfig):
    task_id = f"scrape_{int(time.time())}"
    task = asyncio.create_task(scrape_members_task(task_id, config.source_group, config.limit))
    active_tasks[task_id] = task
    return {"status": "started", "task_id": task_id}

@app.post("/api/add-members")
async def start_adding(config: AddConfig):
    task_id = f"add_{int(time.time())}"
    task = asyncio.create_task(add_members_task(task_id, config.target_group, config.users_per_hour))
    active_tasks[task_id] = task
    return {"status": "started", "task_id": task_id}

@app.post("/api/tasks/{task_id}/{action}")
async def control_task(task_id: str, action: str):
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if action in ['pause', 'resume', 'stop']:
        task_status[task_id]['status'] = action
        return {"status": "success", "action": action}
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

@app.get("/api/tasks")
async def get_tasks():
    return list(task_status.values())

@app.get("/api/stats")
async def get_stats():
    # Total users
    users_result = supabase.table('scraped_users').select('*', count='exact').execute()
    total_users = users_result.count or 0
    
    # Added today
    today = datetime.now().date()
    added_today_result = supabase.table('scraped_users')\
        .select('*', count='exact')\
        .gte('added_at', today.isoformat())\
        .execute()
    added_today = added_today_result.count or 0
    
    # Active tasks
    active_tasks_count = sum(1 for task in task_status.values() if task['status'] == 'running')
    
    return {
        "total_users": total_users,
        "added_today": added_today,
        "active_tasks": active_tasks_count
    }

@app.get("/api/stream")
async def stream_updates():
    """Server-Sent Events for live updates"""
    async def event_generator():
        while True:
            # Send periodic updates
            await asyncio.sleep(2)
            yield f"data: {json.dumps({'type': 'stats_update', 'timestamp': time.time()})}\n\n"
    
    return EventSourceResponse(event_generator())

class EventSourceResponse:
    def __init__(self, generator):
        self.generator = generator
    
    async def __call__(self, scope, receive, send):
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [
                [b'content-type', b'text/event-stream'],
                [b'cache-control', b'no-cache'],
                [b'connection', b'keep-alive'],
            ],
        })
        
        async for chunk in self.generator:
            await send({
                'type': 'http.response.body',
                'body': chunk.encode('utf-8'),
                'more_body': True
            })

# Health check
@app.get("/health")
async def health_check():
    telegram_status = "connected" if client.is_connected() else "disconnected"
    return {
        "status": "healthy",
        "telegram": telegram_status,
        "timestamp": datetime.now().isoformat(),
        "active_tasks": len(active_tasks)
    }

if __name__ == "__main__":
    # Create session file if it doesn't exist
    if not os.path.exists("session.session"):
        open("session.session", "w").close()
    
    setup_directories()
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
