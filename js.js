// Replace the simulate functions with actual API calls
async function startScraping(channel, count) {
    try {
        const response = await fetch('https://tggg-qmzy.onrender.com/api/scrape', {
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
        const response = await fetch('https://tggg-qmzy.onrender.com/api/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({target, count})
        });
        log('Adding started', 'info');
    } catch (error) {
        log(`Error: ${error.message}`, 'error');
    }
}
