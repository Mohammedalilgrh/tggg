// Replace the simulate functions with actual API calls
async function startScraping(channel, count) {
    try {
        const response = await fetch('https://tggg-qmzy.onrender.com/api/scrape', {  // أزل المسافات
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
        const response = await fetch('https://tggg-qmzy.onrender.com/api/add', {  // أزل المسافات
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({target, count})
        });
        log('Adding started', 'info');
    } catch (error) {
        log(`Error: ${error.message}`, 'error');
    }
}

// دالة تنزيل البيانات
async function downloadData() {
    try {
        const response = await fetch('https://tggg-qmzy.onrender.com/api/data/download');
        const data = await response.json();
        
        // إنشاء ملف JSON للتنزيل
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

// دالة تحديث الإحصائيات (من Supabase)
async function updateStats() {
    try {
        const response = await fetch('https://tggg-qmzy.onrender.com/api/stats');
        const stats = await response.json();
        scrapedCountEl.textContent = stats.scraped || 0;
        addedCountEl.textContent = stats.added || 0;
        privacyBlockedEl.textContent = stats.privacyBlocked || 0;
        failedCountEl.textContent = stats.failed || 0;
    } catch (error) {
        console.error('Stats error:', error);
    }
}

// استبدل الدالة simulateScraping
function simulateScraping(channel, count) {
    // استخدم الدالة الحقيقية بدلاً من المحاكاة
    startScraping(channel, count);
}

// استبدل الدالة simulateAdding
function simulateAdding(target, count) {
    // استخدم الدالة الحقيقية بدلاً من المحاكاة
    startAdding(target, count);
}
