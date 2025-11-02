import os
import time
import random
import threading
import asyncio
from flask import Flask, render_template, request, jsonify
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, 
    UserPrivacyRestrictedError,
    PeerFloodError,
    UserNotParticipantError,
    PhoneNumberBannedError
)
from supabase import create_client, Client
import logging
from datetime import datetime, timedelta

# ======================
# CONFIGURATION SETUP
# ======================
API_ID = int(os.getenv("API_ID", "21706160"))
API_HASH = os.getenv("API_HASH", "548b91f0e7cd2e44bbee05190620d9f4")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+96407762476460")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://apseoggiwlcdwzihfthz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFwc2VvZ2dpd2xjZHd6aWhmdGh6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5ODk2NzMsImV4cCI6MjA3NzU2NTY3M30.ZD47Gvm1cFc-oE2hJyoStWHuCvdXFlrxdrgBPucfW0Q")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Anti-ban configuration
DAILY_LIMIT = 40  # Max members added per day
MIN_DELAY = 30    # Minimum seconds between actions
MAX_DELAY = 120   # Maximum seconds between actions
BATCH_SIZE = 5    # Members to process before pausing
PAUSE_BETWEEN_BATCHES = 3600  # 1 hour between batches

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# ======================
# TELEGRAM CLIENT SETUP
# ======================
async def get_client():
    """Initialize Telegram client with session persistence"""
    global SESSION_STRING
    
    # Try to load existing session
    if SESSION_STRING:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    else:
        # Create new session if none exists
        client = TelegramClient('anon', API_ID, API_HASH)
    
    # Handle authentication
    await client.start()
    
    # Save updated session string
    if not SESSION_STRING:
        SESSION_STRING = client.session.save()
        # In production, save this to your environment securely
        logging.info("New session created. Save this SESSION_STRING in your environment variables!")
    
    return client

# ======================
# DATABASE OPERATIONS
# ======================
def init_db():
    """Initialize database tables if they don't exist"""
    try:
        # Check if tables exist
        response = supabase.rpc('init_database').execute()
        logging.info("Database initialized successfully")
    except Exception as e:
        logging.error(f"Database init error: {str(e)}")

def save_session(session_str):
    """Save session string to database"""
    try:
        supabase.table('sessions').upsert({
            'phone': PHONE_NUMBER,
            'session_string': session_str,
            'last_updated': datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        logging.error(f"Session save error: {str(e)}")

def get_daily_count():
    """Get number of members added today"""
    today = datetime.utcnow().date().isoformat()
    try:
        response = supabase.table('added_members').select('count').eq('added_date', today).execute()
        return response.data[0]['count'] if response.data else 0
    except Exception as e:
        logging.error(f"Daily count error: {str(e)}")
        return 0

def log_added_member(user_id, username, source_group, target_group):
    """Log successfully added member"""
    try:
        supabase.table('added_members').insert({
            'user_id': user_id,
            'username': username,
            'source_group': source_group,
            'target_group': target_group,
            'added_date': datetime.utcnow().date().isoformat(),
            'added_time': datetime.utcnow().time().isoformat()
        }).execute()
    except Exception as e:
        logging.error(f"Member log error: {str(e)}")

def is_member_added(user_id):
    """Check if member was already added"""
    try:
        response = supabase.table('added_members').select('user_id').eq('user_id', user_id).limit(1).execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Member check error: {str(e)}")
        return False

# ======================
# TELEGRAM OPERATIONS
# ======================
async def scrape_members(client, group_id, limit):
    """Safely scrape members from a group with anti-ban measures"""
    members = []
    try:
        # Get entity for the group
        entity = await client.get_entity(group_id)
        
        # Get participants with filters
        async for member in client.iter_participants(
            entity,
            limit=limit * 2,  # Fetch extra to account for filters
            aggressive=True
        ):
            # Apply anti-ban filters
            if (member.deleted or 
                member.bot or 
                not member.username or
                is_member_added(member.id)):
                continue
                
            members.append(member)
            if len(members) >= limit:
                break
                
            # Random delay between fetches
            await asyncio.sleep(random.uniform(1, 3))
            
    except Exception as e:
        logging.error(f"Scraping error: {str(e)}")
    
    return members[:limit]

async def add_member_safe(client, target_group, user):
    """Add member with comprehensive error handling and delays"""
    try:
        # Check daily limit before adding
        if get_daily_count() >= DAILY_LIMIT:
            logging.warning("Daily limit reached. Pausing operations.")
            return False, "daily_limit"
            
        # Add member with flood protection
        await client(functions.channels.InviteToChannelRequest(
            channel=target_group,
            users=[user]
        ))
        
        # Log successful addition
        log_added_member(user.id, user.username, "current_source", target_group)
        
        # Random delay after successful add
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        logging.info(f"Added {user.username}. Sleeping for {delay:.1f} seconds")
        await asyncio.sleep(delay)
        
        return True, None
        
    except (FloodWaitError, PeerFloodError) as e:
        wait_time = e.seconds if hasattr(e, 'seconds') else 300
        logging.warning(f"Flood protection triggered. Waiting {wait_time} seconds")
        await asyncio.sleep(wait_time)
        return False, "flood"
        
    except UserPrivacyRestrictedError:
        logging.warning(f"Privacy restricted for {user.username}")
        return False, "privacy"
        
    except UserNotParticipantError:
        logging.warning(f"User not participant: {user.username}")
        return False, "not_participant"
        
    except PhoneNumberBannedError:
        logging.critical("ACCOUNT BANNED! Stopping all operations")
        return False, "banned"
        
    except Exception as e:
        logging.error(f"Unexpected error adding {user.username}: {str(e)}")
        await asyncio.sleep(10)
        return False, "unknown"

# ======================
# JOB MANAGEMENT
# ======================
job_status = {
    'state': 'idle',  # idle, running, paused, stopped
    'progress': 0,
    'total': 0,
    'current_batch': 0,
    'last_action': '',
    'error': None,
    'start_time': None
}
job_lock = threading.Lock()
current_job = None

async def run_job(source_group, target_group, total_members):
    """Main job execution with pause/resume/stop capability"""
    global job_status
    
    async with job_lock:
        client = await get_client()
        
        try:
            # Update job status
            job_status.update({
                'state': 'running',
                'progress': 0,
                'total': total_members,
                'start_time': time.time(),
                'error': None
            })
            
            logging.info(f"Starting job: {total_members} members from {source_group} to {target_group}")
            
            # Process in batches
            remaining = total_members
            batch_num = 1
            
            while remaining > 0 and job_status['state'] != 'stopped':
                # Check pause state
                while job_status['state'] == 'paused':
                    await asyncio.sleep(1)
                    if job_status['state'] == 'stopped':
                        break
                
                if job_status['state'] == 'stopped':
                    break
                
                # Calculate batch size
                batch_size = min(BATCH_SIZE, remaining)
                job_status['current_batch'] = batch_num
                
                # Scrape members for this batch
                job_status['last_action'] = f"Scraping batch {batch_num}"
                members = await scrape_members(client, source_group, batch_size)
                
                if not members:
                    job_status['error'] = "No valid members found to add"
                    break
                
                # Add members
                successful = 0
                for member in members:
                    if job_status['state'] in ['paused', 'stopped']:
                        break
                    
                    job_status['last_action'] = f"Adding {member.username}"
                    success, reason = await add_member_safe(client, target_group, member)
                    
                    if success:
                        successful += 1
                        job_status['progress'] += 1
                    elif reason == "banned":
                        job_status['state'] = 'stopped'
                        job_status['error'] = "Account banned by Telegram"
                        break
                
                # Update remaining count
                remaining -= batch_size
                job_status['last_action'] = f"Batch {batch_num} completed ({successful}/{batch_size} added)"
                
                # Pause between batches if more remaining
                if remaining > 0 and job_status['state'] == 'running':
                    job_status['last_action'] = f"Pausing for {PAUSE_BETWEEN_BATCHES//60} minutes before next batch"
                    for i in range(PAUSE_BETWEEN_BATCHES):
                        if job_status['state'] != 'running':
                            break
                        await asyncio.sleep(1)
                
                batch_num += 1
            
            # Final status update
            if job_status['state'] != 'stopped':
                job_status['state'] = 'completed'
                job_status['last_action'] = "Job completed successfully"
                logging.info("Job completed successfully")
            
        except Exception as e:
            job_status['state'] = 'stopped'
            job_status['error'] = str(e)
            logging.exception("Job failed with exception")
        
        finally:
            await client.disconnect()

# ======================
# FLASK ROUTES
# ======================
@app.route('/')
def index():
    return render_template('index.html', job_status=job_status)

@app.route('/start', methods=['POST'])
def start_job():
    global current_job
    
    with job_lock:
        if job_status['state'] in ['running', 'paused']:
            return jsonify({'error': 'Job already running'}), 400
        
        data = request.json
        source = data.get('source')
        target = data.get('target')
        count = int(data.get('count', 0))
        
        if not all([source, target, count]):
            return jsonify({'error': 'Missing parameters'}), 400
        
        if count > DAILY_LIMIT:
            return jsonify({'error': f'Max {DAILY_LIMIT} members per day allowed'}), 400
        
        # Reset job status
        job_status.update({
            'state': 'running',
            'progress': 0,
            'total': count,
            'current_batch': 0,
            'last_action': 'Initializing...',
            'error': None
        })
        
        # Start job in background thread
        def job_wrapper():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_job(source, target, count))
        
        current_job = threading.Thread(target=job_wrapper, daemon=True)
        current_job.start()
        
        return jsonify({'status': 'started'})

@app.route('/control', methods=['POST'])
def job_control():
    action = request.json.get('action')
    
    with job_lock:
        if action == 'pause' and job_status['state'] == 'running':
            job_status['state'] = 'paused'
            return jsonify({'status': 'paused'})
        
        elif action == 'resume' and job_status['state'] == 'paused':
            job_status['state'] = 'running'
            return jsonify({'status': 'resumed'})
        
        elif action == 'stop':
            job_status['state'] = 'stopped'
            return jsonify({'status': 'stopped'})
        
        return jsonify({'error': 'Invalid action or state'}), 400

@app.route('/status')
def job_status_endpoint():
    elapsed = 0
    if job_status['start_time'] and job_status['state'] == 'running':
        elapsed = time.time() - job_status['start_time']
    
    return jsonify({
        'state': job_status['state'],
        'progress': job_status['progress'],
        'total': job_status['total'],
        'percent': int(job_status['progress'] / job_status['total'] * 100) if job_status['total'] else 0,
        'current_batch': job_status['current_batch'],
        'last_action': job_status['last_action'],
        'error': job_status['error'],
        'elapsed': round(elapsed),
        'remaining': max(0, job_status['total'] - job_status['progress'])
    })

# ======================
# HTML TEMPLATE
# ======================
@app.route('/health')
def health_check():
    return jsonify(status="ok", timestamp=datetime.utcnow().isoformat())

# ======================
# INITIALIZATION
# ======================
def init_app():
    """Initialize application components"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Initialize database
    init_db()
    
    # Load session from database if available
    global SESSION_STRING
    try:
        response = supabase.table('sessions').select('session_string').eq('phone', PHONE_NUMBER).execute()
        if response.data and len(response.data) > 0:
            SESSION_STRING = response.data[0]['session_string']
            logging.info("Loaded session from database")
    except Exception as e:
        logging.error(f"Session load error: {str(e)}")

if __name__ == '__main__':
    init_app()
    
    # Start Flask in production mode
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
