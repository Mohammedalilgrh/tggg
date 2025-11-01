import asyncio
import json
import os
from datetime import datetime
from telethon import TelegramClient, functions, types
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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

# صفحة ويب مدمجة
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Telegram Member Scraper & Adder</title>
        <style>
            :root {
                --primary: #3498db;
                --success: #2ecc71;
                --danger: #e74c3c;
                --warning: #f39c12;
                --dark: #1a1a1a;
                --darker: #0d0d0d;
                --light: #f5f5f5;
                --gray: #2d2d2d;
                --card: #1e1e1e;
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            body {
                background-color: var(--dark);
                color: var(--light);
                line-height: 1.6;
            }
            
            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }
            
            header {
                background: linear-gradient(135deg, var(--primary), #1a5276);
                color: white;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 30px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            }
            
            h1 {
                font-size: 2.2rem;
                margin-bottom: 10px;
            }
            
            .subtitle {
                font-size: 1.1rem;
                opacity: 0.9;
            }
            
            .dashboard {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 25px;
                margin-bottom: 30px;
            }
            
            .card {
                background: var(--card);
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.2);
                padding: 25px;
                transition: transform 0.3s ease;
            }
            
            .card:hover {
                transform: translateY(-5px);
            }
            
            .card h2 {
                color: white;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid var(--gray);
            }
            
            .form-group {
                margin-bottom: 20px;
            }
            
            label {
                display: block;
                margin-bottom: 8px;
                font-weight: 600;
                color: #ddd;
            }
            
            input, select, button {
                width: 100%;
                padding: 12px;
                border: 1px solid #333;
                border-radius: 6px;
                font-size: 16px;
                background: #2d2d2d;
                color: white;
            }
            
            button {
                background: var(--primary);
                color: white;
                border: none;
                cursor: pointer;
                font-weight: 600;
                transition: background 0.3s;
            }
            
            button:hover {
                background: #2980b9;
            }
            
            .btn-group {
                display: flex;
                gap: 10px;
            }
            
            .btn-group button {
                flex: 1;
            }
            
            .btn-stop {
                background: var(--danger);
            }
            
            .btn-stop:hover {
                background: #c0392b;
            }
            
            .btn-pause {
                background: var(--warning);
            }
            
            .btn-pause:hover {
                background: #d35400;
            }
            
            .btn-download {
                background: #9b59b6;
            }
            
            .btn-download:hover {
                background: #8e44ad;
            }
            
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-top: 20px;
            }
            
            .stat-card {
                background: var(--gray);
                padding: 15px;
                border-radius: 8px;
                text-align: center;
            }
            
            .stat-value {
                font-size: 2rem;
                font-weight: 700;
                color: var(--primary);
            }
            
            .stat-label {
                font-size: 0.9rem;
                color: #aaa;
            }
            
            .log-container {
                background: #111;
                color: #f8f8f2;
                padding: 20px;
                border-radius: 8px;
                height: 300px;
                overflow-y: auto;
                font-family: monospace;
                font-size: 14px;
            }
            
            .log-entry {
                margin-bottom: 5px;
                padding: 5px;
                border-left: 3px solid var(--primary);
            }
            
            .log-info { border-left-color: var(--primary); }
            .log-success { border-left-color: var(--success); }
            .log-warning { border-left-color: var(--warning); }
            .log-error { border-left-color: var(--danger); }
            
            .status-indicator {
                display: inline-block;
                width: 12px;
                height: 12px;
                border-radius: 50%;
                margin-right: 8px;
            }
            
            .status-active {
                background-color: var(--success);
                box-shadow: 0 0 8px var(--success);
            }
            
            .status-inactive {
                background-color: var(--danger);
            }
            
            .status-paused {
                background-color: var(--warning);
            }
            
            @media (max-width: 768px) {
                .dashboard {
                    grid-template-columns: 1fr;
                }
                
                .btn-group {
                    flex-direction: column;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>🚀 Telegram Member Scraper & Adder</h1>
                <p class="subtitle">Professional tool with anti-ban protection and continuous operation</p>
            </header>
            
            <div class="dashboard">
                <!-- Scrape Section -->
                <div class="card">
                    <h2>📊 Channel Scraper</h2>
                    <div class="form-group">
                        <label for="sourceChannel">Source Channel/Group (@username)</label>
                        <input type="text" id="sourceChannel" placeholder="@example_channel">
                    </div>
                    <div class="form-group">
                        <label for="scrapeCount">Number of Members to Scrape (0 = all)</label>
                        <input type="number" id="scrapeCount" value="0" min="0">
                    </div>
                    <button id="startScrape">Start Scraping</button>
                </div>
                
                <!-- Add Members Section -->
                <div class="card">
                    <h2>👥 Add Members</h2>
                    <div class="form-group">
                        <label for="targetChannel">Target Channel/Group (@username)</label>
                        <input type="text" id="targetChannel" placeholder="@target_group">
                    </div>
                    <div class="form-group">
                        <label for="addCount">Number of Members to Add (0 = all)</label>
                        <input type="number" id="addCount" value="0" min="0">
                    </div>
                    <div class="btn-group">
                        <button id="startAdd">Start Adding</button>
                        <button id="pauseAdd" class="btn-pause">Pause</button>
                        <button id="stopAdd" class="btn-stop">Stop</button>
                    </div>
                </div>
                
                <!-- Settings Section -->
                <div class="card">
                    <h2>⚙️ Settings</h2>
                    <div class="form-group">
                        <label for="minDelay">Minimum Delay (seconds)</label>
                        <input type="number" id="minDelay" value="35" min="10">
                    </div>
                    <div class="form-group">
                        <label for="maxDelay">Maximum Delay (seconds)</label>
                        <input type="number" id="maxDelay" value="95" min="20">
                    </div>
                    <div class="form-group">
                        <label for="sessionLimit">Session Limit</label>
                        <input type="number" id="sessionLimit" value="500" min="100">
                    </div>
                    <button id="saveSettings">Save Settings</button>
                </div>
            </div>
            
            <!-- Data Management -->
            <div class="card">
                <h2>💾 Data Management</h2>
                <div class="btn-group">
                    <button id="downloadData" class="btn-download" onclick="downloadData()">Download Scraped Data</button>
                    <button id="clearData">Clear Local Data</button>
                </div>
            </div>
            
            <!-- Stats Section -->
            <div class="card">
                <h2>📈 Operation Statistics</h2>
                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-value" id="scrapedCount">0</div>
                        <div class="stat-label">Scraped</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="addedCount">0</div>
                        <div class="stat-label">Added</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="privacyBlocked">0</div>
                        <div class="stat-label">Privacy Blocked</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="failedCount">0</div>
                        <div class="stat-label">Failed</div>
                    </div>
                </div>
            </div>
            
            <!-- Status & Logs -->
            <div class="card">
                <h2>📋 Status & Logs</h2>
                <p>Status: <span class="status-indicator status-inactive" id="statusIndicator"></span> <span id="statusText">Inactive</span></p>
                <div class="log-container" id="logContainer">
                    <div class="log-entry log-info">System initialized. Ready to start operations.</div>
                </div>
            </div>
        </div>

        <script>
            // DOM Elements
            const startScrapeBtn = document.getElementById('startScrape');
            const startAddBtn = document.getElementById('startAdd');
            const pauseAddBtn = document.getElementById('pauseAdd');
            const stopAddBtn = document.getElementById('stopAdd');
            const saveSettingsBtn = document.getElementById('saveSettings');
            const downloadDataBtn = document.getElementById('downloadData');
            const clearDataBtn = document.getElementById('clearData');
            const logContainer = document.getElementById('logContainer');
            const statusIndicator = document.getElementById('statusIndicator');
            const statusText = document.getElementById('statusText');
            
            // Stats elements
            const scrapedCountEl = document.getElementById('scrapedCount');
            const addedCountEl = document.getElementById('addedCount');
            const privacyBlockedEl = document.getElementById('privacyBlocked');
            const failedCountEl = document.getElementById('failedCount');
            
            // State management
            let isScraping = false;
            let isAdding = false;
            let isPaused = false;
            
            // Log function
            function log(message, type = 'info') {
                const timestamp = new Date().toLocaleTimeString();
                const logEntry = document.createElement('div');
                logEntry.className = `log-entry log-${type}`;
                logEntry.textContent = `[${timestamp}] ${message}`;
                logContainer.appendChild(logEntry);
                logContainer.scrollTop = logContainer.scrollHeight;
            }
            
            // Update status indicator
            function updateStatus(status) {
                const statusMap = {
                    inactive: { class: 'status-inactive', text: 'Inactive' },
                    active: { class: 'status-active', text: 'Active' },
                    paused: { class: 'status-paused', text: 'Paused' }
                };
                
                const statusInfo = statusMap[status] || statusMap.inactive;
                statusIndicator.className = `status-indicator ${statusInfo.class}`;
                statusText.textContent = statusInfo.text;
            }
            
            // Update stats (from API)
            async function updateStats() {
                try {
                    const response = await fetch('/api/stats');  // غير الرابط
                    const stats = await response.json();
                    scrapedCountEl.textContent = stats.scraped || 0;
                    addedCountEl.textContent = stats.added || 0;
                    privacyBlockedEl.textContent = stats.privacyBlocked || 0;
                    failedCountEl.textContent = stats.failed || 0;
                } catch (error) {
                    console.error('Stats error:', error);
                }
            }
            
            // API functions
            async function startScraping(channel, count) {
                try {
                    const response = await fetch('/api/scrape', {  // غير الرابط
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({channel, count})
                    });
                    const data = await response.json();
                    log(`Scraping started: ${data.scraped_count} members`, 'info');
                } catch (error) {
                    log(`Error: ${error.message}`, 'error');
                }
            }

            async function startAdding(target, count) {
                try {
                    const response = await fetch('/api/add', {  // غير الرابط
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({target, count})
                    });
                    log('Adding started', 'info');
                } catch (error) {
                    log(`Error: ${error.message}`, 'error');
                }
            }

            async function downloadData() {
                try {
                    const response = await fetch('/api/data/download');  // غير الرابط
                    const data = await response.json();
                    
                    // Create downloadable JSON file
                    const dataStr = JSON.stringify(data.users, null, 2);
                    const blob = new Blob([dataStr], {type: 'application/json'});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'scraped_data.json';
                    a.click();
                    URL.revokeObjectURL(url);
                    
                    log('Data downloaded successfully', 'success');
                } catch (error) {
                    log(`Download error: ${error.message}`, 'error');
                }
            }

            // Event Listeners
            startScrapeBtn.addEventListener('click', () => {
                const channel = document.getElementById('sourceChannel').value;
                const count = document.getElementById('scrapeCount').value;
                
                if (!channel) {
                    log('Please enter a source channel', 'error');
                    return;
                }
                
                log(`Starting to scrape from: ${channel} (${count === '0' ? 'all' : count} members)`, 'info');
                isScraping = true;
                updateStatus('active');
                startScraping(channel, count);
            });
            
            startAddBtn.addEventListener('click', () => {
                const target = document.getElementById('targetChannel').value;
                const count = document.getElementById('addCount').value;
                
                if (!target) {
                    log('Please enter a target channel', 'error');
                    return;
                }
                
                log(`Starting to add members to: ${target} (${count === '0' ? 'all' : count} members)`, 'info');
                isAdding = true;
                isPaused = false;
                updateStatus('active');
                startAdding(target, count);
            });
            
            pauseAddBtn.addEventListener('click', () => {
                if (!isAdding) return;
                
                isPaused = !isPaused;
                updateStatus(isPaused ? 'paused' : 'active');
                log(isPaused ? 'Operation paused' : 'Operation resumed', 'warning');
            });
            
            stopAddBtn.addEventListener('click', () => {
                if (!isAdding && !isScraping) return;
                
                isAdding = false;
                isScraping = false;
                isPaused = false;
                updateStatus('inactive');
                log('Operation stopped', 'info');
            });
            
            saveSettingsBtn.addEventListener('click', () => {
                updateStats();
                log('Stats refreshed', 'info');
            });
            
            clearDataBtn.addEventListener('click', () => {
                log('Local data cleared', 'info');
            });
            
            // Initialize
            log('Tool initialized. Ready to use.', 'success');
        </script>
    </body>
    </html>
    """

class TelegramScraper:
    def __init__(self):
        self.api_id = os.getenv("API_ID")
        self.api_hash = os.getenv("API_HASH")
        self.client = TelegramClient('session', self.api_id, self.api_hash)
        self.scraped_users = []

    async def start_client(self):
        try:
            await self.client.start()
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

scraper = TelegramScraper()

@app.on_event("startup")
async def startup_event():
    await scraper.start_client()

@app.post("/api/scrape")
async def start_scraping(channel: str, count: int = 0):
    members = await scraper.scrape_channel_members(channel)
    return {"status": "success", "scraped_count": len(members)}

@app.post("/api/add")
async def start_adding(target: str, count: int = 0):
    # Add member adding logic here
    return {"status": "success"}

@app.get("/api/data/download")
async def download_scraped_data():
    try:
        data, count = supabase.table('scraped_users').select('*').execute()
        return {"users": data[1]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/stats")
async def get_stats():
    return {
        "scraped": len(scraper.scraped_users),
        "added": 0,
        "privacy_blocked": 0,
        "failed": 0
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
