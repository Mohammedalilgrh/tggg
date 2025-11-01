import os
import asyncio
import json
import time
import random
from datetime import datetime
from typing import List, Optional, Dict, Any
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
from telethon import TelegramClient, functions, types
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError
from supabase import create_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
API_ID = "21706160"
API_HASH = "548b91f0e7cd2e44bbee05190620d9f4"
SESSION_STRING = "session"
PHONE_NUMBER = "+96407762476460"
SUPABASE_URL = "https://apseoggiwlcdwzihfthz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFwc2VvZ2dpd2xjZHd6aWhmdGh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5ODk2NzMsImV4cCI6MjA3NzU2NTY3M30.ZD47Gvm1cFc-oE2hJyoStWHuCvdXFlrxdrgBPucfW0Q"

# Initialize Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Global variables
active_tasks = {}
task_status = {}

# HTML Interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Telegram Manager</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #0f0f23; color: white; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: #1a1a2e; padding: 20px; margin: 20px 0; border-radius: 10px; border: 1px solid #333; }
        button { background: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin: 5px; }
        button:hover { opacity: 0.8; }
        .btn-pause { background: #ff9800; }
        .btn-stop { background: #f44336; }
        input, select { width: 100%; padding: 10px; margin: 5px 0; border-radius: 5px; border: 1px solid #333; background: #2a2a3e; color: white; }
        .progress { width: 100%; background: #333; border-radius: 5px; margin: 10px 0; }
        .progress-bar { height: 20px; background: #4CAF50; border-radius: 5px; width: 0%; transition: width 0.3s; }
        .log { background: #000; padding: 10px; border-radius: 5px; height: 200px; overflow-y: scroll; font-family: monospace; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Telegram Group Manager</h1>
        
        <div class="card">
            <h2>🔍 Scrape Members</h2>
            <input type="text" id="sourceGroup" placeholder="Source Group @username" value="@telegram">
            <input type="number" id="scrapeLimit" placeholder="Limit" value="100">
            <button onclick="startScraping()">Start Scraping</button>
        </div>

        <div class="card">
            <h2>📤 Add Members</h2>
            <input type="text" id="targetGroup" placeholder="Target Group @username" value="@username">
            <select id="usersPerHour">
                <option value="10">10/hour (Safe)</option>
                <option value="20">20/hour (Normal)</option>
                <option value="30">30/hour (Fast)</option>
            </select>
            <button onclick="startAdding()">Start Adding</button>
        </div>

        <div class="card">
            <h2>📊 Active Tasks</h2>
            <div id="tasks"></div>
        </div>

        <div class="card">
            <h2>📝 Live Logs</h2>
            <div id="log" class="log"></div>
        </div>
    </div>

    <script>
        function log(message) {
            const logDiv = document.getElementById('log');
            logDiv.innerHTML += '[' + new Date().toLocaleTimeString() + '] ' + message + '\\n';
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        async function startScraping() {
            const sourceGroup = document.getElementById('sourceGroup').value;
            const limit = document.getElementById('scrapeLimit').value;
            
            log('Starting scraping from: ' + sourceGroup);
            
            const response = await fetch('/api/scrape', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({source_group: sourceGroup, limit: parseInt(limit)})
            });
            
            const data = await response.json();
            log('Scraping started: ' + data.task_id);
            updateTasks();
        }

        async function startAdding() {
            const targetGroup = document.getElementById('targetGroup').value;
            const usersPerHour = document.getElementById('usersPerHour').value;
            
            log('Starting adding to: ' + targetGroup);
            
            const response = await fetch('/api/add-members', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target_group: targetGroup, users_per_hour: parseInt(usersPerHour)})
            });
            
            const data = await response.json();
            log('Adding started: ' + data.task_id);
            updateTasks();
        }

        async function controlTask(taskId, action) {
            await fetch('/api/tasks/' + taskId + '/' + action, {method: 'POST'});
            log('Task ' + taskId + ' ' + action);
            updateTasks();
        }

        async function updateTasks() {
            const response = await fetch('/api/tasks');
            const tasks = await response.json();
            
            const tasksDiv = document.getElementById('tasks');
            tasksDiv.innerHTML = '';
            
            tasks.forEach(task => {
                const taskDiv = document.createElement('div');
                taskDiv.className = 'card';
                taskDiv.innerHTML = `
                    <h3>${task.type.toUpperCase()} - ${task.status}</h3>
                    <p>${task.message}</p>
                    <div class="progress">
                        <div class="progress-bar" style="width: ${task.progress}%"></div>
                    </div>
                    <p>Progress: ${task.progress}%</p>
                    <button class="btn-pause" onclick="controlTask('${task.task_id}', 'pause')">Pause</button>
                    <button onclick="controlTask('${task.task_id}', 'resume')">Resume</button>
                    <button class="btn-stop" onclick="controlTask('${task.task_id}', 'stop')">Stop</button>
                `;
                tasksDiv.appendChild(taskDiv);
            });
        }

        // Update tasks every 3 seconds
        setInterval(updateTasks, 3000);
        
        // Initial load
        updateTasks();
        log('System ready - Powered by Telethon');
    </script>
</body>
</html>
"""

# Initialize FastAPI app
app = FastAPI()

# Telegram client
client = None

@app.on_event("startup")
async def startup():
    global client
    client = TelegramClient(SESSION_STRING, int(API_ID), API_HASH)
    await client.start(phone=PHONE_NUMBER)
    logger.info("Telegram client started")

@app.on_event("shutdown")
async def shutdown():
    if client:
        await client.disconnect()
        logger.info("Telegram client disconnected")

@app.get("/")
async def home():
    return HTMLResponse(HTML_TEMPLATE)

@app.post("/api/scrape")
async def scrape_members(request: dict):
    source_group = request.get('source_group')
    limit = request.get('limit', 100)
    
    task_id = f"scrape_{int(time.time())}"
    
    async def scrape_task():
        try:
            task_status[task_id] = {'status': 'running', 'progress': 0, 'message': 'Starting...', 'type': 'scrape', 'task_id': task_id}
            
            # Get group entity
            entity = await client.get_entity(source_group)
            participants = await client.get_participants(entity, limit=limit)
            
            total = len(participants)
            for i, user in enumerate(participants):
                if task_status[task_id]['status'] == 'stopped':
                    break
                    
                while task_status[task_id]['status'] == 'paused':
                    await asyncio.sleep(1)
                
                # Save user to database
                user_data = {
                    'id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'phone': user.phone,
                    'scraped_at': datetime.now().isoformat()
                }
                
                supabase.table('scraped_users').upsert(user_data).execute()
                
                progress = int((i + 1) / total * 100)
                task_status[task_id].update({
                    'progress': progress,
                    'message': f'Scraped {i+1}/{total} users'
                })
                
                await asyncio.sleep(0.1)
            
            if task_status[task_id]['status'] != 'stopped':
                task_status[task_id]['status'] = 'completed'
                task_status[task_id]['message'] = f'Completed: {total} users scraped'
                
        except Exception as e:
            task_status[task_id]['status'] = 'error'
            task_status[task_id]['message'] = f'Error: {str(e)}'
    
    asyncio.create_task(scrape_task())
    return {'status': 'started', 'task_id': task_id}

@app.post("/api/add-members")
async def add_members(request: dict):
    target_group = request.get('target_group')
    users_per_hour = request.get('users_per_hour', 20)
    
    task_id = f"add_{int(time.time())}"
    
    async def add_task():
        try:
            task_status[task_id] = {'status': 'running', 'progress': 0, 'message': 'Starting...', 'type': 'add', 'task_id': task_id}
            
            # Get target group
            target_entity = await client.get_entity(target_group)
            
            # Get users to add
            users = supabase.table('scraped_users').select('*').is_('added_to_group', 'null').execute().data
            
            total = len(users)
            added = 0
            
            for i, user in enumerate(users):
                if task_status[task_id]['status'] == 'stopped':
                    break
                    
                while task_status[task_id]['status'] == 'paused':
                    await asyncio.sleep(1)
                
                try:
                    # Add user to group
                    await client(functions.channels.InviteToChannelRequest(
                        channel=target_entity,
                        users=[user['id']]
                    ))
                    
                    # Mark as added
                    supabase.table('scraped_users').update({
                        'added_to_group': target_group,
                        'added_at': datetime.now().isoformat()
                    }).eq('id', user['id']).execute()
                    
                    added += 1
                    
                    progress = int((i + 1) / total * 100)
                    task_status[task_id].update({
                        'progress': progress,
                        'message': f'Added {added}/{total} users'
                    })
                    
                    # Safe delay
                    delay = random.uniform(30, 60)
                    await asyncio.sleep(delay)
                    
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 10)
                except Exception as e:
                    continue
            
            if task_status[task_id]['status'] != 'stopped':
                task_status[task_id]['status'] = 'completed'
                task_status[task_id]['message'] = f'Completed: {added} users added'
                
        except Exception as e:
            task_status[task_id]['status'] = 'error'
            task_status[task_id]['message'] = f'Error: {str(e)}'
    
    asyncio.create_task(add_task())
    return {'status': 'started', 'task_id': task_id}

@app.post("/api/tasks/{task_id}/{action}")
async def control_task(task_id: str, action: str):
    if task_id in task_status:
        if action in ['pause', 'resume', 'stop']:
            task_status[task_id]['status'] = action
            return {'status': 'success'}
    return {'status': 'error', 'message': 'Task not found'}

@app.get("/api/tasks")
async def get_tasks():
    return list(task_status.values())

@app.get("/health")
async def health():
    return {'status': 'healthy', 'timestamp': datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
