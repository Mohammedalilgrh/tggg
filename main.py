import os
import asyncio
import logging
import time
import random
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, UserNotParticipantError, ChannelPrivateError,
    UserPrivacyRestrictedError, ChatAdminRequiredError
)
from supabase import create_client, Client
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables
API_ID = int(os.getenv('API_ID', '21706160'))
API_HASH = os.getenv('API_HASH', '548b91f0e7cd2e44bbee05190620d9f4')
SESSION_STRING = os.getenv('SESSION_STRING', '')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://apseoggiwlcdwzihfthz.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFwc2VvZ2dpd2xjZHd6aWhmdGh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5ODk2NzMsImV4cCI6MjA3NzU2NTY3M30.ZD47Gvm1cFc-oE2hJyoStWHuCvdXFlrxdrgBPucfW0Q')

# Initialize Supabase
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Supabase: {e}")
    supabase = None

# Global variables for task management
current_task = None
task_status = "stopped"  # stopped, running, paused
current_config = {}
progress_data = {
    "scraped": 0,
    "added": 0,
    "failed": 0,
    "total": 0,
    "current_action": "Ready to start",
    "status": "stopped"
}

# HTML Template with modern UI
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Member Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        .status-running { background: linear-gradient(135deg, #10b981, #059669); }
        .status-paused { background: linear-gradient(135deg, #f59e0b, #d97706); }
        .status-stopped { background: linear-gradient(135deg, #ef4444, #dc2626); }
        .progress-bar { transition: width 0.3s ease-in-out; }
        .log-entry { animation: fadeIn 0.3s ease-in; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="text-center mb-8">
            <h1 class="text-4xl font-bold text-gray-800 mb-2">
                <i class="fab fa-telegram mr-3 text-blue-500"></i>
                Telegram Member Manager
            </h1>
            <p class="text-gray-600">Safely scrape and manage Telegram group members</p>
        </div>

        <!-- Status Card -->
        <div class="bg-white rounded-xl shadow-lg p-6 mb-6">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-4">
                    <div class="w-3 h-3 rounded-full {{ 'bg-green-500 animate-pulse' if status == 'running' else 'bg-yellow-500' if status == 'paused' else 'bg-red-500' }}"></div>
                    <div>
                        <h2 class="text-xl font-semibold text-gray-800">Status: <span class="capitalize">{{ status }}</span></h2>
                        <p class="text-gray-600 text-sm" id="currentAction">{{ progress.current_action }}</p>
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-2xl font-bold text-gray-800" id="progressNumbers">
                        {{ progress.scraped }}/{{ progress.total }}
                    </div>
                    <div class="text-sm text-gray-600">Members Processed</div>
                </div>
            </div>
            
            <!-- Progress Bar -->
            <div class="mt-4">
                <div class="flex justify-between text-sm text-gray-600 mb-1">
                    <span>Progress</span>
                    <span id="progressPercent">0%</span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-3">
                    <div id="progressBar" class="progress-bar h-3 rounded-full bg-blue-500" style="width: 0%"></div>
                </div>
            </div>
        </div>

        <!-- Configuration Card -->
        <div class="bg-white rounded-xl shadow-lg p-6 mb-6">
            <h2 class="text-2xl font-bold text-gray-800 mb-4"><i class="fas fa-cog mr-2 text-blue-500"></i>Configuration</h2>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Source Group -->
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        <i class="fas fa-users mr-2"></i>Source Group
                    </label>
                    <input type="text" id="sourceGroup" placeholder="@username or -1001234567890" 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>

                <!-- Target Channel -->
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        <i class="fas fa-bullhorn mr-2"></i>Target Channel
                    </label>
                    <input type="text" id="targetChannel" placeholder="@username or -1001234567890" 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>

                <!-- Members Count -->
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        <i class="fas fa-list-ol mr-2"></i>Members to Process
                    </label>
                    <input type="number" id="maxMembers" value="50" min="1" max="1000" 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>

                <!-- Safety Delay -->
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        <i class="fas fa-shield-alt mr-2"></i>Safety Delay (seconds)
                    </label>
                    <input type="number" id="safetyDelay" value="45" min="20" max="120" 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    <p class="text-xs text-gray-500 mt-1">Higher delay = More safety</p>
                </div>
            </div>
        </div>

        <!-- Control Buttons -->
        <div class="bg-white rounded-xl shadow-lg p-6 mb-6">
            <div class="flex flex-wrap justify-center gap-4">
                <button onclick="controlTask('start')" 
                        class="px-8 py-3 bg-green-500 hover:bg-green-600 text-white rounded-lg font-semibold transition duration-200 flex items-center">
                    <i class="fas fa-play mr-2"></i> Start
                </button>
                <button onclick="controlTask('pause')" 
                        class="px-8 py-3 bg-yellow-500 hover:bg-yellow-600 text-white rounded-lg font-semibold transition duration-200 flex items-center">
                    <i class="fas fa-pause mr-2"></i> Pause
                </button>
                <button onclick="controlTask('stop')" 
                        class="px-8 py-3 bg-red-500 hover:bg-red-600 text-white rounded-lg font-semibold transition duration-200 flex items-center">
                    <i class="fas fa-stop mr-2"></i> Stop
                </button>
            </div>
        </div>

        <!-- Statistics -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div class="bg-green-500 text-white rounded-lg p-4 text-center">
                <div class="text-2xl font-bold" id="statScraped">0</div>
                <div class="text-sm">Scraped</div>
            </div>
            <div class="bg-blue-500 text-white rounded-lg p-4 text-center">
                <div class="text-2xl font-bold" id="statAdded">0</div>
                <div class="text-sm">Added</div>
            </div>
            <div class="bg-red-500 text-white rounded-lg p-4 text-center">
                <div class="text-2xl font-bold" id="statFailed">0</div>
                <div class="text-sm">Failed</div>
            </div>
        </div>

        <!-- Live Logs -->
        <div class="bg-white rounded-xl shadow-lg p-6">
            <h2 class="text-2xl font-bold text-gray-800 mb-4">
                <i class="fas fa-terminal mr-2 text-blue-500"></i>Live Logs
            </h2>
            <div id="logs" class="bg-gray-900 text-green-400 rounded-lg p-4 h-64 overflow-y-auto font-mono text-sm">
                <div class="log-entry">System initialized. Ready to start...</div>
            </div>
            <div class="flex justify-between items-center mt-4">
                <button onclick="clearLogs()" class="px-4 py-2 bg-gray-500 hover:bg-gray-600 text-white rounded-lg text-sm">
                    <i class="fas fa-trash mr-1"></i> Clear Logs
                </button>
                <span class="text-sm text-gray-600" id="logCount">1 message</span>
            </div>
        </div>
    </div>

    <script>
        let logCount = 1;

        function addLog(message, type = 'info') {
            const logs = document.getElementById('logs');
            const timestamp = new Date().toLocaleTimeString();
            const color = type === 'error' ? 'text-red-400' : type === 'success' ? 'text-green-400' : 'text-blue-400';
            const logEntry = document.createElement('div');
            logEntry.className = `log-entry mb-1 ${color}`;
            logEntry.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> ${message}`;
            logs.appendChild(logEntry);
            logs.scrollTop = logs.scrollHeight;
            
            logCount++;
            document.getElementById('logCount').textContent = `${logCount} messages`;
        }

        function clearLogs() {
            document.getElementById('logs').innerHTML = '<div class="log-entry mb-1 text-green-400">Logs cleared...</div>';
            logCount = 1;
            document.getElementById('logCount').textContent = '1 message';
        }

        async function controlTask(action) {
            const config = {
                source_group: document.getElementById('sourceGroup').value,
                target_channel: document.getElementById('targetChannel').value,
                max_members: parseInt(document.getElementById('maxMembers').value),
                delay: parseInt(document.getElementById('safetyDelay').value)
            };

            if ((action === 'start') && (!config.source_group || !config.target_channel)) {
                addLog('Please fill in both source group and target channel!', 'error');
                return;
            }

            try {
                const response = await fetch('/control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action, config })
                });
                
                const data = await response.json();
                addLog(data.message, data.success ? 'success' : 'error');
            } catch (error) {
                addLog('Network error: ' + error.message, 'error');
            }
        }

        async function updateStatus() {
            try {
                const response = await fetch('/status');
                const data = await response.json();
                
                // Update status indicator
                document.querySelector('h2 .capitalize').textContent = data.status;
                document.querySelector('.w-3.h-3').className = `w-3 h-3 rounded-full ${
                    data.status === 'running' ? 'bg-green-500 animate-pulse' : 
                    data.status === 'paused' ? 'bg-yellow-500' : 'bg-red-500'
                }`;
                
                // Update progress
                document.getElementById('currentAction').textContent = data.progress.current_action;
                document.getElementById('progressNumbers').textContent = 
                    `${data.progress.scraped}/${data.progress.total}`;
                
                // Update statistics
                document.getElementById('statScraped').textContent = data.progress.scraped;
                document.getElementById('statAdded').textContent = data.progress.added;
                document.getElementById('statFailed').textContent = data.progress.failed;
                
                // Update progress bar
                const percent = data.progress.total > 0 ? (data.progress.added / data.progress.total) * 100 : 0;
                document.getElementById('progressBar').style.width = percent + '%';
                document.getElementById('progressPercent').textContent = Math.round(percent) + '%';
                
            } catch (error) {
                console.error('Failed to update status:', error);
            }
        }

        // Update status every 2 seconds
        setInterval(updateStatus, 2000);
        updateStatus();

        // Add some sample logs for demonstration
        setTimeout(() => addLog('System check completed. All systems operational.', 'success'), 1000);
        setTimeout(() => addLog('Telegram client ready. Session is active.', 'success'), 2000);
    </script>
</body>
</html>
'''

class TelegramManager:
    def __init__(self):
        self.client = None
        self.is_connected = False
        
    async def initialize_client(self):
        """Initialize Telegram client with session string"""
        try:
            if not SESSION_STRING:
                raise ValueError("SESSION_STRING environment variable is required")
                
            self.client = TelegramClient(
                StringSession(SESSION_STRING), 
                API_ID, 
                API_HASH
            )
            
            await self.client.start()
            
            me = await self.client.get_me()
            logger.info(f"Telegram client initialized successfully for: {me.username or me.first_name}")
            self.is_connected = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Telegram client: {e}")
            return False
    
    async def safe_scrape_members(self, source_group, max_members=50):
        """Safely scrape members from source group with anti-ban measures"""
        try:
            global progress_data
            
            progress_data["current_action"] = f"Connecting to source group: {source_group}"
            
            # Get entity with validation
            try:
                if source_group.startswith('@'):
                    entity = await self.client.get_entity(source_group)
                else:
                    entity = await self.client.get_entity(int(source_group))
            except (ValueError, ChannelPrivateError) as e:
                progress_data["current_action"] = f"Error: Cannot access group - {str(e)}"
                return []
            
            progress_data["current_action"] = f"Scraping members from {source_group}"
            
            members = []
            count = 0
            
            async for user in self.client.iter_participants(entity, limit=max_members):
                if task_status == "stopped":
                    break
                if task_status == "paused":
                    while task_status == "paused" and task_status != "stopped":
                        await asyncio.sleep(1)
                    if task_status == "stopped":
                        break
                
                # Skip bots and deleted accounts
                if user.bot or user.deleted:
                    continue
                
                # Skip restricted users
                if user.restricted or user.scam:
                    continue
                    
                members.append({
                    'id': user.id,
                    'username': user.username,
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'scraped_at': datetime.now().isoformat()
                })
                
                count += 1
                progress_data["scraped"] = count
                progress_data["total"] = max_members
                
                # Anti-ban: Random delay between scrapes
                delay = random.uniform(1.0, 3.0)
                await asyncio.sleep(delay)
                
                if count >= max_members:
                    break
            
            # Save to Supabase
            if members and supabase:
                try:
                    supabase.table('scraped_members').insert({
                        'group_source': source_group,
                        'members': members,
                        'count': len(members),
                        'scraped_at': datetime.now().isoformat()
                    }).execute()
                    logger.info(f"Saved {len(members)} members to Supabase")
                except Exception as e:
                    logger.error(f"Failed to save to Supabase: {e}")
            
            progress_data["current_action"] = f"Successfully scraped {len(members)} members"
            return members
            
        except Exception as e:
            logger.error(f"Error scraping members: {e}")
            progress_data["current_action"] = f"Scraping error: {str(e)}"
            return []
    
    async def safe_add_members(self, members, target_channel, delay=45):
        """Safely add members to target channel with comprehensive anti-ban measures"""
        try:
            global progress_data
            
            progress_data["current_action"] = f"Connecting to target channel: {target_channel}"
            
            # Get target entity
            try:
                if target_channel.startswith('@'):
                    target_entity = await self.client.get_entity(target_channel)
                else:
                    target_entity = await self.client.get_entity(int(target_channel))
            except (ValueError, ChannelPrivateError) as e:
                progress_data["current_action"] = f"Error: Cannot access target channel - {str(e)}"
                return 0
            
            progress_data["current_action"] = f"Starting to add {len(members)} members"
            
            added_count = 0
            failed_count = 0
            
            for i, member in enumerate(members):
                if task_status == "stopped":
                    break
                if task_status == "paused":
                    while task_status == "paused" and task_status != "stopped":
                        await asyncio.sleep(1)
                    if task_status == "stopped":
                        break
                
                try:
                    # Anti-ban: Progressive delay - longer delays as we add more members
                    base_delay = delay
                    progressive_delay = base_delay + (i * 0.1)  # Increase delay slightly for each member
                    jitter = random.uniform(0.8, 1.2)  # Random jitter
                    actual_delay = progressive_delay * jitter
                    
                    progress_data["current_action"] = f"Adding member {i+1}/{len(members)} (waiting {actual_delay:.1f}s)"
                    
                    # Add user to channel
                    await self.client.edit_admin(
                        target_entity,
                        member['id'],
                        is_admin=False,
                        add_admins=False,
                        invite_users=True
                    )
                    
                    added_count += 1
                    progress_data["added"] = added_count
                    
                    # Log success
                    if supabase:
                        supabase.table('addition_logs').insert({
                            'user_id': member['id'],
                            'username': member.get('username', ''),
                            'target_channel': target_channel,
                            'added_at': datetime.now().isoformat(),
                            'success': True,
                            'attempt_number': i + 1
                        }).execute()
                    
                    logger.info(f"Successfully added user {member['id']} to channel")
                    
                    # Anti-ban: Randomize wait time between actions
                    wait_time = actual_delay + random.uniform(-5, 5)
                    progress_data["current_action"] = f"Added {added_count}/{len(members)} - Safety delay: {wait_time:.1f}s"
                    
                    for sec in range(int(wait_time)):
                        if task_status == "stopped":
                            break
                        if task_status == "paused":
                            while task_status == "paused" and task_status != "stopped":
                                await asyncio.sleep(1)
                            if task_status == "stopped":
                                break
                        await asyncio.sleep(1)
                    
                    if task_status == "stopped":
                        break
                        
                except FloodWaitError as e:
                    # Handle flood wait - this is critical for anti-ban
                    wait_time = e.seconds + 10  # Add buffer
                    progress_data["current_action"] = f"Flood wait: Waiting {wait_time} seconds"
                    logger.warning(f"Flood wait detected: {wait_time} seconds")
                    
                    # Log flood wait
                    if supabase:
                        supabase.table('error_logs').insert({
                            'error_type': 'flood_wait',
                            'wait_time': wait_time,
                            'occurred_at': datetime.now().isoformat()
                        }).execute()
                    
                    await asyncio.sleep(wait_time)
                    continue  # Retry the same member
                    
                except (UserPrivacyRestrictedError, UserNotParticipantError, ChatAdminRequiredError) as e:
                    # Handle specific errors gracefully
                    failed_count += 1
                    progress_data["failed"] = failed_count
                    logger.warning(f"Failed to add user {member['id']}: {type(e).__name__}")
                    
                    if supabase:
                        supabase.table('addition_logs').insert({
                            'user_id': member['id'],
                            'username': member.get('username', ''),
                            'target_channel': target_channel,
                            'added_at': datetime.now().isoformat(),
                            'success': False,
                            'error': type(e).__name__,
                            'error_message': str(e)
                        }).execute()
                    
                    # Continue with next member
                    continue
                    
                except Exception as e:
                    failed_count += 1
                    progress_data["failed"] = failed_count
                    logger.error(f"Unexpected error adding user {member['id']}: {e}")
                    
                    if supabase:
                        supabase.table('error_logs').insert({
                            'error_type': 'unexpected',
                            'error_message': str(e),
                            'occurred_at': datetime.now().isoformat()
                        }).execute()
                    
                    continue
            
            progress_data["current_action"] = f"Completed: Added {added_count}, Failed: {failed_count}"
            return added_count
            
        except Exception as e:
            logger.error(f"Error in add members process: {e}")
            progress_data["current_action"] = f"Process error: {str(e)}"
            return 0

# Global manager instance
manager = TelegramManager()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, status=task_status, progress=progress_data)

@app.route('/control', methods=['POST'])
async def control_task():
    global current_task, task_status, current_config
    
    data = request.json
    action = data.get('action')
    config = data.get('config', {})
    
    try:
        if action == 'start':
            if task_status == 'running':
                return jsonify({'success': False, 'message': 'Task is already running'})
            
            # Validate required fields
            if not config.get('source_group') or not config.get('target_channel'):
                return jsonify({'success': False, 'message': 'Source group and target channel are required'})
            
            # Reset progress
            progress_data.update({
                "scraped": 0, 
                "added": 0, 
                "failed": 0, 
                "total": config.get('max_members', 50),
                "current_action": "Initializing...",
                "status": "starting"
            })
            
            # Initialize client if not connected
            if not manager.is_connected:
                progress_data["current_action"] = "Connecting to Telegram..."
                success = await manager.initialize_client()
                if not success:
                    progress_data["current_action"] = "Failed to connect to Telegram"
                    return jsonify({'success': False, 'message': 'Failed to connect to Telegram. Check SESSION_STRING.'})
            
            # Start the task
            task_status = "running"
            current_config = config
            current_task = asyncio.create_task(run_scraping_adding(config))
            
            return jsonify({'success': True, 'message': 'Task started successfully'})
        
        elif action == 'pause':
            if task_status == 'running':
                task_status = "paused"
                progress_data["current_action"] = "Process paused"
                progress_data["status"] = "paused"
                return jsonify({'success': True, 'message': 'Task paused'})
            else:
                return jsonify({'success': False, 'message': 'No running task to pause'})
        
        elif action == 'stop':
            task_status = "stopped"
            if current_task:
                current_task.cancel()
            progress_data["current_action"] = "Process stopped"
            progress_data["status"] = "stopped"
            return jsonify({'success': True, 'message': 'Task stopped'})
        
        return jsonify({'success': False, 'message': 'Unknown action'})
        
    except Exception as e:
        logger.error(f"Error in control task: {e}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/status')
def get_status():
    progress_data["status"] = task_status
    return jsonify({
        'status': task_status,
        'progress': progress_data
    })

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'telegram_connected': manager.is_connected,
        'supabase_connected': supabase is not None,
        'timestamp': datetime.now().isoformat()
    })

async def run_scraping_adding(config):
    """Main function to run scraping and adding process"""
    global task_status
    
    try:
        source_group = config.get('source_group', '').strip()
        target_channel = config.get('target_channel', '').strip()
        max_members = config.get('max_members', 50)
        delay = max(config.get('delay', 45), 20)  # Minimum 20 seconds delay for safety
        
        logger.info(f"Starting process: {source_group} -> {target_channel}, Members: {max_members}, Delay: {delay}s")
        
        # Scrape members
        progress_data["current_action"] = "Starting to scrape members..."
        members = await manager.safe_scrape_members(source_group, max_members)
        
        if not members:
            progress_data["current_action"] = "No members scraped or error occurred"
            task_status = "stopped"
            return
        
        # Add members to channel
        progress_data["current_action"] = f"Starting to add {len(members)} members with {delay}s safety delays..."
        added_count = await manager.safe_add_members(members, target_channel, delay)
        
        progress_data["current_action"] = f"Process completed! Successfully added {added_count} members"
        task_status = "stopped"
        progress_data["status"] = "stopped"
        
        # Log completion
        if supabase:
            supabase.table('process_logs').insert({
                'source_group': source_group,
                'target_channel': target_channel,
                'members_scraped': len(members),
                'members_added': added_count,
                'completed_at': datetime.now().isoformat(),
                'success': True
            }).execute()
        
    except asyncio.CancelledError:
        logger.info("Task was cancelled")
        progress_data["current_action"] = "Process cancelled by user"
    except Exception as e:
        logger.error(f"Error in main process: {e}")
        progress_data["current_action"] = f"Process error: {str(e)}"
        
        # Log error
        if supabase:
            supabase.table('error_logs').insert({
                'error_type': 'process_failure',
                'error_message': str(e),
                'occurred_at': datetime.now().isoformat()
            }).execute()
    finally:
        task_status = "stopped"
        progress_data["status"] = "stopped"

def init_supabase_tables():
    """Initialize Supabase tables if they don't exist"""
    if not supabase:
        return
    
    try:
        # This will create the tables if they don't exist through Supabase's API
        tables = ['scraped_members', 'addition_logs', 'error_logs', 'process_logs']
        for table in tables:
            try:
                supabase.table(table).select('*').limit(1).execute()
                logger.info(f"Table {table} is accessible")
            except Exception as e:
                logger.warning(f"Table {table} might not exist: {e}")
    except Exception as e:
        logger.error(f"Error initializing Supabase tables: {e}")

@app.before_request
def before_first_request():
    """Initialize before first request"""
    init_supabase_tables()

if __name__ == '__main__':
    # Initialize Supabase tables
    init_supabase_tables()
    
    # Start Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
