import asyncio
import logging
import os
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import create_client, Client
from telethon import TelegramClient
from telethon.errors import FloodWaitError, PeerFloodError, UserPrivacyRestrictedError, UserNotMutualContactError
import random
import time

# --- Configuration ---
API_ID = os.getenv("API_ID", "21706160")
API_HASH = os.getenv("API_HASH", "548b91f0e7cd2e44bbee05190620d9f4")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+96407762476460")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://apseoggiwlcdwzihfthz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFwc2VvZ2dpd2xjZHd6aWhmdGh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5ODk2NzMsImV4cCI6MjA3NzU2NTY3M30.ZD47Gvm1cFc-oE2hJyoStWHuCvdXFlrxdrgBPucfW0Q")

# --- Supabase Client ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- FastAPI App Setup ---
app = FastAPI()

# --- Telethon Client Setup ---
client: TelegramClient = TelegramClient('sessions.sessions', API_ID, API_HASH)

# --- Global Variables ---
is_running = False
is_paused = False
current_task = None
scraped_members = []
target_group = None
source_group = None
num_to_scrape = 0
num_to_add = 0
operation_stats = {"scraped": 0, "added": 0, "errors": 0}
settings = {
    "min_delay": 35,
    "max_delay": 95,
    "session_limit": 500
}

# --- Pydantic Models ---
class ScrapeConfig(BaseModel):
    source_group: str
    num_to_scrape: int

class AddConfig(BaseModel):
    target_group: str
    num_to_add: int

class SettingsConfig(BaseModel):
    min_delay: int
    max_delay: int
    session_limit: int

# --- Helper Functions ---

def safe_delay():
    """Introduce a random delay between min/max to avoid detection."""
    delay = random.uniform(settings["min_delay"], settings["max_delay"])
    time.sleep(delay)

def save_settings_to_db():
    """Save current settings to Supabase."""
    try:
        data, count = supabase.table('settings').upsert({
            "id": 1,
            "min_delay": settings["min_delay"],
            "max_delay": settings["max_delay"],
            "session_limit": settings["session_limit"]
        }).execute()
        logging.info("Settings saved to Supabase.")
    except Exception as e:
        logging.error(f"Error saving settings: {e}")

def load_settings_from_db():
    """Load settings from Supabase."""
    global settings
    try:
        data, count = supabase.table('settings').select("*").eq('id', 1).execute()
        if data.get('data'):
            row = data['data'][0]
            settings["min_delay"] = row.get("min_delay", 35)
            settings["max_delay"] = row.get("max_delay", 95)
            settings["session_limit"] = row.get("session_limit", 500)
        logging.info("Settings loaded from Supabase.")
    except Exception as e:
        logging.error(f"Error loading settings: {e}")

def save_members_to_db(members):
    """Save scraped members to Supabase using the scraped_users table."""
    try:
        for member in members:
            data, count = supabase.table('scraped_users').insert({
                "id": member.id,
                "username": member.username or "",
                "first_name": member.first_name,
                "last_name": member.last_name or "",
                "phone": getattr(member, 'phone', None),
                "is_premium": getattr(member, 'premium', False),
                "scraped_at": datetime.utcnow().isoformat(),
                "added_to_group": None, # Initially not added
                "added_at": None
            }).execute()
        logging.info(f"Saved {len(members)} members to Supabase.")
    except Exception as e:
        logging.error(f"Error saving members to Supabase: {e}")

async def add_members_with_protection(target_group_id, members_to_add):
    """Add members to target group with anti-ban protection."""
    global operation_stats
    added_count = 0
    
    for i, user_id in enumerate(members_to_add):
        if not is_running or is_paused:
            logging.info("Addition process paused or stopped.")
            break

        try:
            logging.info(f"Adding user {user_id} to {target_group_id}")
            await client(telethon.functions.channels.InviteToChannelRequest(
                channel=target_group_id,
                users=[user_id]
            ))
            operation_stats["added"] += 1
            added_count += 1
            
            # Update the database to mark user as added
            try:
                supabase.table('scraped_users').update({
                    "added_to_group": target_group_id,
                    "added_at": datetime.utcnow().isoformat()
                }).eq('id', user_id).execute()
            except Exception as db_err:
                logging.error(f"Error updating database for user {user_id}: {db_err}")

            # Delay after every 5 adds
            if (i + 1) % 5 == 0:
                logging.info(f"Batch delay: 300 seconds...")
                await asyncio.sleep(300)
            else:
                safe_delay()

        except FloodWaitError as e:
            logging.warning(f"FloodWait: Sleeping for {e.seconds} seconds.")
            await asyncio.sleep(e.seconds)
            continue
        except PeerFloodError:
            logging.error("PeerFlood error. Stopping to avoid ban.")
            is_running = False
            break
        except UserPrivacyRestrictedError:
            logging.warning(f"User {user_id} has privacy restrictions.")
            operation_stats["errors"] += 1
        except UserNotMutualContactError:
            logging.warning(f"User {user_id} is not a mutual contact, skipping.")
            operation_stats["errors"] += 1
        except Exception as e:
            logging.error(f"Unexpected error adding user {user_id}: {e}")
            operation_stats["errors"] += 1

async def run_scraping_and_adding():
    global is_running, is_paused, scraped_members, target_group, num_to_scrape, source_group, operation_stats
    is_running = True
    operation_stats = {"scraped": 0, "added": 0, "errors": 0}
    
    try:
        await client.start() # Use the existing session file
        logging.info("Telethon client started with session file.")

        # Scrape Members
        logging.info(f"Scraping from: {source_group}, limit: {num_to_scrape}")
        entity = await client.get_entity(source_group)
        async for member in client.iter_participants(entity, limit=num_to_scrape):
            if not is_running or is_paused:
                break
            scraped_members.append(member)
            operation_stats["scraped"] += 1
            logging.info(f"Scraped: {member.first_name} (@{member.username or 'N/A'})")

        logging.info(f"Scraping finished. Total scraped: {len(scraped_members)}")
        save_members_to_db(scraped_members)

        # Add Members (if target is specified and num_to_add > 0)
        if target_group and num_to_add > 0:
            members_to_add = [m.id for m in scraped_members[:num_to_add]]
            logging.info(f"Starting to add {len(members_to_add)} members to {target_group}")
            await add_members_with_protection(target_group, members_to_add)
        else:
            logging.info("No target group or members to add specified.")

    except Exception as e:
        logging.error(f"Error in main process: {e}")
    finally:
        is_running = False
        logging.info("Process finished or stopped.")

# --- FastAPI Routes ---

@app.get("/", response_class=HTMLResponse)
async def index():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Telegram Member Tool</title>
        <style>
            :root {
                --primary: #1e88e5;
                --secondary: #ff9800;
                --danger: #e53935;
                --dark-bg: #121212;
                --card-bg: #1e1e1e;
                --text: #ffffff;
                --border: #333333;
            }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: var(--dark-bg);
                color: var(--text);
                margin: 0;
                padding: 0;
                line-height: 1.6;
            }
            .header {
                background: linear-gradient(135deg, #007bff, #0056b3);
                color: white;
                padding: 15px 20px;
                text-align: center;
                border-bottom: 2px solid rgba(255,255,255,0.1);
                box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            }
            .container {
                max-width: 1200px;
                margin: 20px auto;
                padding: 20px;
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
            }
            .card {
                background-color: var(--card-bg);
                border-radius: 10px;
                padding: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);
                border: 1px solid var(--border);
            }
            .card h2 {
                margin-top: 0;
                color: var(--text);
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .card h2::before {
                content: '';
                width: 24px;
                height: 24px;
                background-size: contain;
                background-repeat: no-repeat;
            }
            .card input, .card button {
                width: 100%;
                padding: 10px;
                margin: 8px 0;
                border-radius: 5px;
                border: 1px solid var(--border);
                background-color: #2d2d2d;
                color: var(--text);
                font-size: 14px;
            }
            .card input:focus, .card button:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 2px rgba(30, 136, 229, 0.2);
            }
            .btn {
                padding: 12px 20px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-weight: bold;
                transition: all 0.3s ease;
                text-align: center;
            }
            .btn-primary {
                background-color: var(--primary);
                color: white;
            }
            .btn-secondary {
                background-color: var(--secondary);
                color: white;
            }
            .btn-danger {
                background-color: var(--danger);
                color: white;
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            }
            .btn-primary:hover {
                background-color: #1976d2;
            }
            .btn-secondary:hover {
                background-color: #fb8c00;
            }
            .btn-danger:hover {
                background-color: #d32f2f;
            }
            .status-panel {
                grid-column: 1 / -1;
                background-color: var(--card-bg);
                padding: 15px;
                border-radius: 10px;
                margin-top: 20px;
            }
            .stats {
                display: flex;
                justify-content: space-around;
                flex-wrap: wrap;
                gap: 15px;
                margin-top: 15px;
                padding: 15px;
                background-color: #1a1a1a;
                border-radius: 8px;
            }
            .stat-item {
                text-align: center;
                padding: 10px;
                border-radius: 5px;
                background-color: #2d2d2d;
                min-width: 120px;
            }
            .live-review {
                margin-top: 20px;
                padding: 15px;
                background-color: #1a1a1a;
                border-radius: 8px;
            }
            .live-review h3 {
                margin-top: 0;
                border-bottom: 1px solid var(--border);
                padding-bottom: 10px;
            }
            .member-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .member-list li {
                padding: 8px 12px;
                border-bottom: 1px solid var(--border);
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .member-list li:last-child {
                border-bottom: none;
            }
            .member-avatar {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background-color: #444;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 14px;
            }
            .member-name {
                flex: 1;
            }
            .member-username {
                font-size: 12px;
                color: #aaa;
            }
            @media (max-width: 768px) {
                .container {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Telegram Member Scraper & Adder</h1>
            <p>Professional tool with anti-ban protection and continuous operation</p>
        </div>

        <div class="container">
            <!-- Channel Scraper Panel -->
            <div class="card">
                <h2>📊 Channel Scraper</h2>
                <div class="form-group">
                    <label>Source Channel/Group (@username)</label>
                    <input type="text" id="sourceGroup" placeholder="@GC_BV" value="@GC_BV">
                </div>
                <div class="form-group">
                    <label>Number of Members to Scrape (0 = all)</label>
                    <input type="number" id="numToScrape" value="50" min="0">
                </div>
                <button class="btn btn-primary" onclick="startScraping()">Start Scraping</button>
            </div>

            <!-- Add Members Panel -->
            <div class="card">
                <h2>👥 Add Members</h2>
                <div class="form-group">
                    <label>Target Channel/Group (@username)</label>
                    <input type="text" id="targetGroup" placeholder="@target_group" value="@target_group">
                </div>
                <div class="form-group">
                    <label>Number of Members to Add (0 = all)</label>
                    <input type="number" id="numToAdd" value="0" min="0">
                </div>
                <div style="display: flex; gap: 10px;">
                    <button class="btn btn-primary" onclick="startAdding()">Start Adding</button>
                    <button class="btn btn-secondary" onclick="pauseOperation()">Pause</button>
                    <button class="btn btn-danger" onclick="stopOperation()">Stop</button>
                </div>
            </div>

            <!-- Settings Panel -->
            <div class="card">
                <h2>⚙️ Settings</h2>
                <div class="form-group">
                    <label>Minimum Delay (seconds)</label>
                    <input type="number" id="minDelay" value="35" min="1">
                </div>
                <div class="form-group">
                    <label>Maximum Delay (seconds)</label>
                    <input type="number" id="maxDelay" value="95" min="1">
                </div>
                <div class="form-group">
                    <label>Session Limit</label>
                    <input type="number" id="sessionLimit" value="500" min="1">
                </div>
                <button class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
            </div>

            <!-- Data Management Panel -->
            <div class="card">
                <h2>📁 Data Management</h2>
                <p>Manage scraped data directly from Supabase.</p>
                <button class="btn btn-secondary" onclick="alert('Implemented in Supabase dashboard')">Open Supabase</button>
            </div>

            <!-- Operation Statistics Panel -->
            <div class="card">
                <h2>📈 Operation Statistics</h2>
                <div class="stats">
                    <div class="stat-item">
                        <div id="scrapedCount">0</div>
                        <div>Members Scraped</div>
                    </div>
                    <div class="stat-item">
                        <div id="addedCount">0</div>
                        <div>Members Added</div>
                    </div>
                    <div class="stat-item">
                        <div id="errorCount">0</div>
                        <div>Errors</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Status & Logs Panel -->
        <div class="status-panel">
            <h2>Status & Logs</h2>
            <div id="status">Status: Inactive</div>
            
            <div class="live-review">
                <h3>Live Review (Last 5 Scraped)</h3>
                <ul class="member-list" id="memberList">
                    <li><div class="member-avatar">?</div><div class="member-name">No members yet</div></li>
                </ul>
            </div>
        </div>

        <script>
            let statusInterval;
            let statsInterval;

            // Initialize
            document.addEventListener('DOMContentLoaded', function() {
                loadSettings();
                startPolling();
            });

            async function loadSettings() {
                try {
                    const response = await fetch('/settings');
                    const data = await response.json();
                    if (data.settings) {
                        document.getElementById('minDelay').value = data.settings.min_delay || 35;
                        document.getElementById('maxDelay').value = data.settings.max_delay || 95;
                        document.getElementById('sessionLimit').value = data.settings.session_limit || 500;
                    }
                } catch (error) {
                    console.error('Error loading settings:', error);
                }
            }

            function startPolling() {
                if(statusInterval) clearInterval(statusInterval);
                if(statsInterval) clearInterval(statsInterval);
                
                statusInterval = setInterval(fetchStatus, 5000);
                statsInterval = setInterval(fetchStats, 5000);
                // Initial calls
                fetchStatus();
                fetchStats();
            }

            async function fetchStatus() {
                try {
                    const response = await fetch('/status');
                    const data = await response.json();
                    document.getElementById('status').innerText = `Status: ${data.status}`;
                } catch (error) {
                    console.error('Error fetching status:', error);
                }
            }

            async function fetchStats() {
                try {
                    const response = await fetch('/stats');
                    const data = await response.json();
                    document.getElementById('scrapedCount').innerText = data.scraped;
                    document.getElementById('addedCount').innerText = data.added;
                    document.getElementById('errorCount').innerText = data.errors;
                    
                    // Update live review
                    const memberList = document.getElementById('memberList');
                    memberList.innerHTML = ''; // Clear list
                    
                    if (data.last_scraped && data.last_scraped.length > 0) {
                        data.last_scraped.forEach(m => {
                            const li = document.createElement('li');
                            const avatar = document.createElement('div');
                            avatar.className = 'member-avatar';
                            avatar.textContent = m.first_name ? m.first_name[0].toUpperCase() : '?';
                            
                            const nameDiv = document.createElement('div');
                            nameDiv.className = 'member-name';
                            nameDiv.textContent = m.first_name;
                            
                            const usernameDiv = document.createElement('div');
                            usernameDiv.className = 'member-username';
                            usernameDiv.textContent = `@${m.username || 'N/A'}`;
                            
                            li.appendChild(avatar);
                            li.appendChild(nameDiv);
                            li.appendChild(usernameDiv);
                            memberList.appendChild(li);
                        });
                    } else {
                        const li = document.createElement('li');
                        li.innerHTML = '<div class="member-avatar">?</div><div class="member-name">No members yet</div>';
                        memberList.appendChild(li);
                    }
                } catch (error) {
                    console.error('Error fetching stats:', error);
                }
            }

            async function startScraping() {
                const source = document.getElementById('sourceGroup').value.trim();
                const num = parseInt(document.getElementById('numToScrape').value);
                
                if (!source || num < 0) {
                    alert('Please provide valid source group and number of members.');
                    return;
                }

                try {
                    const response = await fetch('/start-scraping', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ source_group: source, num_to_scrape: num })
                    });
                    const result = await response.json();
                    alert(result.message);
                    if(response.ok) {
                        updateStatus("Active");
                        startPolling();
                    }
                } catch (error) {
                    console.error('Error starting scraping:', error);
                    alert('Failed to start scraping. Check logs.');
                }
            }

            async function startAdding() {
                const target = document.getElementById('targetGroup').value.trim();
                const num = parseInt(document.getElementById('numToAdd').value);
                
                if (!target) {
                    alert('Please provide target group.');
                    return;
                }

                try {
                    const response = await fetch('/start-adding', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_group: target, num_to_add: num })
                    });
                    const result = await response.json();
                    alert(result.message);
                    if(response.ok) {
                        updateStatus("Active");
                        startPolling();
                    }
                } catch (error) {
                    console.error('Error starting adding:', error);
                    alert('Failed to start adding. Check logs.');
                }
            }

            async function pauseOperation() {
                try {
                    const response = await fetch('/control/pause', { method: 'POST' });
                    const result = await response.json();
                    alert(result.message);
                } catch (error) {
                    console.error('Error pausing:', error);
                }
            }

            async function stopOperation() {
                try {
                    const response = await fetch('/control/stop', { method: 'POST' });
                    const result = await response.json();
                    alert(result.message);
                } catch (error) {
                    console.error('Error stopping:', error);
                }
            }

            async function saveSettings() {
                const minDelay = parseInt(document.getElementById('minDelay').value);
                const maxDelay = parseInt(document.getElementById('maxDelay').value);
                const sessionLimit = parseInt(document.getElementById('sessionLimit').value);
                
                if (isNaN(minDelay) || isNaN(maxDelay) || isNaN(sessionLimit)) {
                    alert('Please enter valid numbers for settings.');
                    return;
                }

                try {
                    const response = await fetch('/save-settings', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ 
                            min_delay: minDelay, 
                            max_delay: maxDelay, 
                            session_limit: sessionLimit 
                        })
                    });
                    const result = await response.json();
                    alert(result.message);
                } catch (error) {
                    console.error('Error saving settings:', error);
                    alert('Failed to save settings.');
                }
            }

            function updateStatus(newStatus) {
                document.getElementById('status').innerText = `Status: ${newStatus}`;
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post('/start-scraping')
async def start_scraping(config: ScrapeConfig):
    global source_group, num_to_scrape, is_running, current_task
    if is_running:
        raise HTTPException(status_code=400, detail="Process is already running!")

    source_group = config.source_group
    num_to_scrape = config.num_to_scrape

    if not source_group or num_to_scrape < 0:
        raise HTTPException(status_code=400, detail="Invalid configuration.")

    def run_in_thread():
        asyncio.run(run_scraping_and_adding())

    current_task = asyncio.create_task(asyncio.get_event_loop().run_in_executor(None, run_in_thread))

    return {"message": "Scraping started successfully!"}

@app.post('/start-adding')
async def start_adding(config: AddConfig):
    global target_group, num_to_add, is_running, current_task
    if is_running:
        raise HTTPException(status_code=400, detail="Process is already running!")

    target_group = config.target_group
    num_to_add = config.num_to_add

    if not target_group:
        raise HTTPException(status_code=400, detail="Target group is required.")

    def run_in_thread():
        asyncio.run(run_scraping_and_adding())

    current_task = asyncio.create_task(asyncio.get_event_loop().run_in_executor(None, run_in_thread))

    return {"message": "Adding members started successfully!"}

@app.post('/control/{action}')
async def control_process(action: str):
    global is_running, is_paused
    if action == 'pause':
        is_paused = True
        return {"message": "Process paused."}
    elif action == 'resume':
        is_paused = False
        return {"message": "Process resumed."}
    elif action == 'stop':
        is_running = False
        is_paused = False
        return {"message": "Process stopped."}
    else:
        raise HTTPException(status_code=400, detail="Invalid action.")

@app.get('/status')
async def get_status():
    if is_running and is_paused:
        status = "Paused"
    elif is_running:
        status = "Active"
    else:
        status = "Inactive"
    return {"status": status}

@app.get('/stats')
async def get_stats():
    last_few = scraped_members[-5:] if scraped_members else []
    last_names = [{"first_name": m.first_name, "username": m.username} for m in last_few]
    return {**operation_stats, "last_scraped": last_names}

@app.get('/settings')
async def get_settings():
    return {"settings": settings}

@app.post('/save-settings')
async def save_settings(config: SettingsConfig):
    global settings
    settings["min_delay"] = config.min_delay
    settings["max_delay"] = config.max_delay
    settings["session_limit"] = config.session_limit
    save_settings_to_db()
    return {"message": "Settings saved successfully!"}

if __name__ == '__main__':
    # Load settings on startup
    load_settings_from_db()
    
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Run the FastAPI app with uvicorn
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
```
