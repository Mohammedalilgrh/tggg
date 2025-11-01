async function startScraping(channel, count) {
    try {
        const formData = new FormData();
        formData.append('channel', channel);
        formData.append('count', count || 0);
        
        const response = await fetch('/api/scrape', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        log(`Scraping started: ${data.scraped_count} members`, 'info');
    } catch (error) {
        log(`Error: ${error.message}`, 'error');
    }
}

// استبدل startAdding:
async function startAdding(target, count) {
    try {
        const formData = new FormData();
        formData.append('target', target);
        formData.append('count', count || 0);
        
        const response = await fetch('/api/add', {
            method: 'POST',
            body: formData
        });
        log('Adding started', 'info');
    } catch (error) {
        log(`Error: ${error.message}`, 'error');
    }
}
