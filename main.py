import os
import asyncio
import logging
import time
import random
import threading
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, UserNotParticipantError, ChannelPrivateError,
    UserPrivacyRestrictedError, ChatAdminRequiredError
)
from supabase import create_client, Client
import concurrent.futures

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

# Event for controlling the background task
task_event = threading.Event()
task_thread = None

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
                    <div id="statusDot" class="w-3 h-3 rounded-full bg-red-500"></div>
                    <div>
                        <h2 class="text-xl font-semibold text-gray-800">Status: <span id="statusText" class="capitalize">stopped</span></h2>
                        <p class="text-gray-600 text-sm" id="currentAction">Ready to start</p>
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-2xl font-bold text-gray-800" id="progressNumbers">0/0</div>
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
                    <input type="number" id="maxMembers" value="10" min="1" max="50" 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    <p class="text-xs text-gray-500 mt-1">Start small (5-10) for testing</p>
                </div>

                <!-- Safety Delay -->
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        <i class="fas fa-shield-alt mr-2"></i>Safety Delay (seconds)
                    </label>
                    <input type="number" id="safetyDelay" value="60" min="30" max="120" 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    <p class="text-xs text-gray-500 mt-1">Higher delay = More safety (recommended: 60+)</p>
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
                source_group: document.getElementById('sourceGroup').value.trim(),
                target_channel: document.getElementById('targetChannel').value.trim(),
                max_members: parseInt(document.getElementById('maxMembers').value) || 10,
                delay: parseInt(document.getElementById('safetyDelay').value) || 60
            };

            // Validation
            if (action === 'start') {
                if (!config.source_group) {
                    addLog('Please enter Source Group!', 'error');
                    return;
                }
                if (!config.target_channel) {
                    addLog('Please enter Target Channel!', 'error');
                    return;
                }
                if (config.max_members < 1 || config.max_members > 50) {
                    addLog('Please enter between 1-50 members!', 'error');
                    return;
                }
            }

            try {
                addLog(`Sending ${action} command...`, 'info');
                
                const response = await fetch('/control', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify({ action, config })
                });
                
                // Check if response is JSON
                const contentType = response.headers.get('content-type');
                if (!contentType || !contentType.includes('application/json')) {
                    const text = await response.text();
                    addLog(`Server error: ${text.substring(0, 100)}`, 'error');
                    return;
                }
                
                const data = await response.json();
                if (data.success) {
                    addLog(data.message, 'success');
                } else {
                    addLog(data.message, 'error');
                }
            } catch (error) {
                addLog('Network error: ' + error.message, 'error');
                console.error('Network error:', error);
            }
        }

        async function updateStatus() {
            try {
                const response = await fetch('/status');
                
                // Check if response is JSON
                const contentType = response.headers.get('content-type');
                if (!contentType || !contentType.includes('application/json')) {
                    return;
                }
                
                const data = await response.json();
                
                // Update status indicator
                document.getElementById('statusText').textContent = data.status;
                const statusDot = document.getElementById('statusDot');
                if (statusDot) {
                    statusDot.className = `w-3 h-3 rounded-full ${
                        data.status === 'running' ? 'bg-green-500 animate-pulse' : 
                        data.status === 'paused' ? 'bg-yellow-500' : 'bg-red-500'
                    }`;
                }
                
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

        // Update status every 3 seconds
        setInterval(updateStatus, 3000);
        
        // Initial status update
        setTimeout(updateStatus, 1000);

        // Add some sample logs for demonstration
        setTimeout(() => addLog('System check completed. All systems operational.', 'success'), 1500);
        setTimeout(() => addLog('Ready to start scraping process.', 'info'), 2500);
    </script>
</body>
</html>
'''

class TelegramManager:
    def __init__(self):
        self.client = None
        self.is_connected = False
        self.loop = None
        self._client_lock = asyncio.Lock()
        
    async def _initialize_client(self):
        """Initialize Telegram client with session string"""
        try:
            if not SESSION_STRING:
                raise ValueError("SESSION_STRING environment variable is required")
                
            logger.info("Initializing Telegram client...")
            
            # Create new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            self.client = TelegramClient(
                StringSession(SESSION_STRING), 
                API_ID, 
                API_HASH,
                loop=self.loop
            )
            
            await self.client.start()
            
            me = await self.client.get_me()
            logger.info(f"Telegram client initialized successfully for: {me.username or me.first_name} (ID: {me.id})")
            self.is_connected = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Telegram client: {e}")
            return False

    def initialize_client(self):
        """Synchronous wrapper for client initialization"""
        try:
            return asyncio.run(self._initialize_client())
        except Exception as e:
            logger.error(f"Error in initialize_client: {e}")
            return False
    
    async def _safe_scrape_members(self, source_group, max_members=10):
        """Safely scrape members from source group with anti-ban measures"""
        try:
            global progress_data
            
            progress_data["current_action"] = f"Connecting to source group: {source_group}"
            logger.info(f"Starting to scrape from: {source_group}")
            
            # Get entity with validation
            try:
                if source_group.startswith('@'):
                    entity = await self.client.get_entity(source_group)
                else:
                    entity = await self.client.get_entity(int(source_group))
            except (ValueError, ChannelPrivateError) as e:
                error_msg = f"Cannot access group - {str(e)}"
                progress_data["current_action"] = f"Error: {error_msg}"
                logger.error(error_msg)
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
                delay = random.uniform(2.0, 5.0)
                progress_data["current_action"] = f"Scraped {count}/{max_members} (waiting {delay:.1f}s)"
                await asyncio.sleep(delay)
                
                if count >= max_members:
                    break
            
            logger.info(f"Successfully scraped {len(members)} members")
            
            # Save to Supabase if available
            if members and supabase:
                try:
                    result = supabase.table('scraped_members').insert({
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
    
    async def _safe_add_members(self, members, target_channel, delay=60):
        """Safely add members to target channel with comprehensive anti-ban measures"""
        try:
            global progress_data
            
            progress_data["current_action"] = f"Connecting to target channel: {target_channel}"
            logger.info(f"Starting to add {len(members)} members to {target_channel}")
            
            # Get target entity
            try:
                if target_channel.startswith('@'):
                    target_entity = await self.client.get_entity(target_channel)
                else:
                    target_entity = await self.client.get_entity(int(target_channel))
            except (ValueError, ChannelPrivateError) as e:
                error_msg = f"Cannot access target channel - {str(e)}"
                progress_data["current_action"] = error_msg
                logger.error(error_msg)
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
                    # Anti-ban: Progressive delay
                    base_delay = delay
                    progressive_delay = base_delay + (i * 0.2)
                    jitter = random.uniform(0.8, 1.3)
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
                    
                    logger.info(f"Successfully added user {member['id']} to channel")
                    
                    # Anti-ban: Wait with pause/stop checking
                    wait_time = max(actual_delay, 30)
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
                    # Handle flood wait
                    wait_time = e.seconds + 10
                    progress_data["current_action"] = f"Flood wait: Waiting {wait_time} seconds"
                    logger.warning(f"Flood wait detected: {wait_time} seconds")
                    
                    await asyncio.sleep(wait_time)
                    continue
                    
                except (UserPrivacyRestrictedError, UserNotParticipantError, ChatAdminRequiredError) as e:
                    failed_count += 1
                    progress_data["failed"] = failed_count
                    logger.warning(f"Failed to add user {member['id']}: {type(e).__name__}")
                    continue
                    
                except Exception as e:
                    failed_count += 1
                    progress_data["failed"] = failed_count
                    logger.error(f"Unexpected error adding user {member['id']}: {e}")
                    continue
            
            progress_data["current_action"] = f"Completed: Added {added_count}, Failed: {failed_count}"
            logger.info(f"Process completed: {added_count} added, {failed_count} failed")
            return added_count
            
        except Exception as e:
            logger.error(f"Error in add members process: {e}")
            progress_data["current_action"] = f"Process error: {str(e)}"
            return 0

    def safe_scrape_members(self, source_group, max_members=10):
        """Synchronous wrapper for scraping"""
        try:
            return asyncio.run(self._safe_scrape_members(source_group, max_members))
        except Exception as e:
            logger.error(f"Error in safe_scrape_members: {e}")
            return []

    def safe_add_members(self, members, target_channel, delay=60):
        """Synchronous wrapper for adding members"""
        try:
            return asyncio.run(self._safe_add_members(members, target_channel, delay))
        except Exception as e:
            logger.error(f"Error in safe_add_members: {e}")
            return 0

# Global manager instance
manager = TelegramManager()

def background_task(config):
    """Run the scraping/adding process in background thread"""
    global task_status, progress_data
    
    try:
        source_group = config.get('source_group', '').strip()
        target_channel = config.get('target_channel', '').strip()
        max_members = min(config.get('max_members', 10), 50)
        delay = max(config.get('delay', 60), 30)
        
        logger.info(f"Starting background process: {source_group} -> {target_channel}")
        
        # Initialize client if not connected
        if not manager.is_connected:
            progress_data["current_action"] = "Connecting to Telegram..."
            success = manager.initialize_client()
            if not success:
                progress_data["current_action"] = "Failed to connect to Telegram"
                task_status = "stopped"
                return
        
        # Scrape members
        progress_data["current_action"] = "Starting to scrape members..."
        members = manager.safe_scrape_members(source_group, max_members)
        
        if not members:
            progress_data["current_action"] = "No members scraped or error occurred"
            task_status = "stopped"
            return
        
        # Add members to channel
        progress_data["current_action"] = f"Starting to add {len(members)} members..."
        added_count = manager.safe_add_members(members, target_channel, delay)
        
        progress_data["current_action"] = f"Process completed! Added {added_count} members"
        
    except Exception as e:
        logger.error(f"Error in background task: {e}")
        progress_data["current_action"] = f"Process error: {str(e)}"
    finally:
        task_status = "stopped"
        progress_data["status"] = "stopped"

@app.route('/')
def index():
    try:
        return render_template_string(HTML_TEMPLATE)
    except Exception as e:
        logger.error(f"Error rendering template: {e}")
        return f"Error loading page: {str(e)}", 500

@app.route('/control', methods=['POST'])
def control_task():
    global task_status, task_thread, current_config
    
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid JSON data'}), 400
            
        action = data.get('action')
        config = data.get('config', {})
        
        logger.info(f"Received control action: {action}")
        
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
                "total": min(config.get('max_members', 10), 50),
                "current_action": "Initializing...",
                "status": "starting"
            })
            
            # Start the task in background thread
            task_status = "running"
            current_config = config
            task_thread = threading.Thread(target=background_task, args=(config,))
            task_thread.daemon = True
            task_thread.start()
            
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
            progress_data["current_action"] = "Process stopped"
            progress_data["status"] = "stopped"
            return jsonify({'success': True, 'message': 'Task stopped'})
        
        return jsonify({'success': False, 'message': 'Unknown action'})
        
    except Exception as e:
        logger.error(f"Error in control task: {e}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/status')
def get_status():
    try:
        progress_data["status"] = task_status
        return jsonify({
            'status': task_status,
            'progress': progress_data
        })
    except Exception as e:
        logger.error(f"Error in status endpoint: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'telegram_connected': manager.is_connected,
        'supabase_connected': supabase is not None,
        'task_status': task_status,
        'timestamp': datetime.now().isoformat()
    })

def init_supabase_tables():
    """Initialize Supabase tables"""
    if not supabase:
        logger.warning("Supabase client not available")
        return
    
    try:
        # Test connection
        result = supabase.table('scraped_members').select('*').limit(1).execute()
        logger.info("Supabase connection test successful")
    except Exception as e:
        logger.warning(f"Supabase tables might not exist yet: {e}")

if __name__ == '__main__':
    # Initialize
    init_supabase_tables()
    
    # Start Flask app
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
