const BASE_API_URL = 'https://your-service.onrender.com/api/'; 

let DEEPFAKE_INPUT;
let NEWS_INPUT;
let DEEPFAKE_BUTTON;
let NEWS_BUTTON;
let FILE_NAME_SPAN;
let lastImageFile = null;

// Newspaper theme styles for dynamic result and spinner components
const styleSheet = document.createElement('style');
styleSheet.innerText = `
    .result-box {
        text-align: left;
        color: #000000;
        font-family: 'Times New Roman', Times, serif;
        box-sizing: border-box;
        width: 100%;
        word-break: break-word;
        overflow-wrap: break-word;
    }
    .result-box .title {
        font-size: clamp(1rem, 2.5vw, 1.15rem);
        font-weight: 700;
        margin-bottom: 8px;
        letter-spacing: 1px;
    }
    .verdict-stamp {
        display: inline-block;
        border: 2px solid #000000;
        padding: 5px 12px;
        font-family: 'Times New Roman', Times, serif;
        font-weight: 800;
        font-size: clamp(0.78rem, 2.2vw, 0.95rem);
        letter-spacing: clamp(0.8px, 0.2vw, 1.5px);
        text-transform: uppercase;
        background: rgba(0, 0, 0, 0.05);
        margin-bottom: 10px;
        max-width: 100%;
        box-sizing: border-box;
        word-break: break-word;
        white-space: normal;
        line-height: 1.35;
    }
    .result-box p {
        word-break: break-word;
        overflow-wrap: break-word;
    }
    .result-box a {
        word-break: break-word;
        overflow-wrap: anywhere;
    }
    .spinner {
        border: 3px solid rgba(0, 0, 0, 0.2);
        border-top: 3px solid #000000; 
        border-radius: 50%;
        width: 16px;
        height: 16px;
        animation: spin 0.8s linear infinite;
        display: inline-block;
        vertical-align: middle;
        margin-right: 8px;
        flex-shrink: 0;
    }
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
document.head.appendChild(styleSheet);

function getBase64Image(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = error => reject(error);
    });
}

function setLoading(buttonElement, isLoading, originalText) {
    if (!buttonElement) return;
    buttonElement.disabled = isLoading;
    
    if (isLoading) {
        buttonElement.innerHTML = `<div class="spinner"></div> ${originalText}`;
    } else {
        buttonElement.innerHTML = originalText;
    }
}

function renderResult(containerElement, result) {
    if (!containerElement) return;
    let resultDiv = document.getElementById(containerElement.id + 'Result');
    
    if (!resultDiv) {
        resultDiv = document.createElement('div');
        resultDiv.id = containerElement.id + 'Result';
        containerElement.parentNode.insertBefore(resultDiv, containerElement.nextSibling);
    }
    
    if (result.status === 'error') {
        resultDiv.className = 'result-box fake';
        resultDiv.innerHTML = `
            <div class="verdict-stamp" style="border-color:#000; background:rgba(0,0,0,0.1);">TELEGRAPH ERROR</div>
            <p style="margin: 6px 0; color: #000;">${result.message}</p>
        `;
        return;
    }

    const isReal = result.is_real;
    const className = isReal ? 'real' : 'fake';
    const classificationLabel = isReal ? 'VERDICT: VERIFIED AUTHENTIC' : 'VERDICT: DETECTED AS DECEPTIVE / FAKE';
    
    let html = `<div class="verdict-stamp">${classificationLabel}</div>`;
    html += `<p style="margin: 8px 0; font-size: 1.05rem; line-height: 1.6; color: #000;">${result.classification_text.replace(/\n/g, '<br>')}</p>`;

    if (result.sources && result.sources.length > 0) {
        const sourcesHtml = result.sources.map(source => `
            <li style="margin-bottom: 5px;"><a href="${source.uri}" target="_blank" style="color:#000000; text-decoration:underline; font-weight:700;">${source.title}</a></li>
        `).join('');
        
        html += `<div style="margin-top: 12px; border-top: 1px dashed #000; padding-top: 10px;">`;
        html += `<p style="font-weight: 700; margin-bottom: 6px; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 1px;">Corroborating Wire Dispatches & Sources:</p>`;
        html += `<ul style="margin-left: 20px; padding: 0; list-style-type: square; color:#000;">${sourcesHtml}</ul></div>`;
    }

    resultDiv.className = `result-box ${className}`;
    resultDiv.innerHTML = html;
}

async function fetchBackend(endpoint, payload) {
    try {
        const response = await fetch(BASE_API_URL + endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const result = await response.json();
        
        if (!response.ok || result.status === 'error') {
            throw new Error(result.message || `HTTP Error ${response.status}`);
        }
        return result;
    } catch (error) {
        console.error("Backend Connection Error:", error);
        
        let message = error.message.includes('Failed to fetch') ? 
                      "Could not connect to Python server (Backend). Please check if AI_Backend_Service.py is running on port 5000." :
                      error.message;
                      
        return { status: 'error', message: message };
    }
}

async function runDeepfakeCheck() {
    if (!lastImageFile || !DEEPFAKE_BUTTON) return;

    const originalText = DEEPFAKE_BUTTON.textContent;
    setLoading(DEEPFAKE_BUTTON, true, 'EXAMINING VISUAL EVIDENCE...');
    
    try {
        const base64Data = await getBase64Image(lastImageFile);
        const payload = {
            image_data: base64Data,
            mime_type: lastImageFile.type
        };

        const result = await fetchBackend('deepfake/analyze', payload);
        renderResult(DEEPFAKE_BUTTON, result);

    } catch (error) {
        renderResult(DEEPFAKE_BUTTON, { status: 'error', message: error.message || "Failed during photographic forensic analysis." });
    } finally {
        setLoading(DEEPFAKE_BUTTON, false, originalText);
    }
}

async function checkFakeNews() {
    if (!NEWS_INPUT || !NEWS_BUTTON) return;
    const newsText = NEWS_INPUT.value.trim();
    if (newsText.length < 20 || NEWS_BUTTON.disabled) return;

    const originalText = NEWS_BUTTON.textContent;
    setLoading(NEWS_BUTTON, true, 'CROSS-REFERENCING DISPATCHES...');

    try {
        const payload = { news_text: newsText };
        const result = await fetchBackend('news/verify', payload);
        renderResult(NEWS_BUTTON, result);

    } catch (error) {
        renderResult(NEWS_BUTTON, { status: 'error', message: error.message || "Failed during wire verification." });
    } finally {
        setLoading(NEWS_BUTTON, false, originalText);
    }
}

function handleImageUpload(event) {
    const file = event.target.files ? event.target.files[0] : null;
    if (file) {
        if (file.size > 4 * 1024 * 1024) { 
            if (FILE_NAME_SPAN) FILE_NAME_SPAN.textContent = "File exceeds limit (Max 4MB)";
            if (DEEPFAKE_BUTTON) DEEPFAKE_BUTTON.disabled = true;
            return;
        }
        lastImageFile = file;
        if (FILE_NAME_SPAN) FILE_NAME_SPAN.textContent = file.name;
        if (DEEPFAKE_BUTTON) DEEPFAKE_BUTTON.disabled = false;
    } else {
        if (FILE_NAME_SPAN) FILE_NAME_SPAN.textContent = "No photographic evidence selected";
        if (DEEPFAKE_BUTTON) DEEPFAKE_BUTTON.disabled = true;
    }
}

// Expose handlers globally
window.runDeepfakeCheck = runDeepfakeCheck;
window.checkFakeNews = checkFakeNews;
window.handleImageUpload = handleImageUpload;

document.addEventListener('DOMContentLoaded', () => {
    DEEPFAKE_INPUT = document.getElementById('deepfakeInput');
    NEWS_INPUT = document.getElementById('newsInput') || document.querySelector('textarea');
    DEEPFAKE_BUTTON = document.getElementById('deepfakeButton') || document.querySelector('#deepfakeBox button');
    NEWS_BUTTON = document.getElementById('newsButton') || document.querySelector('#newsBox button');
    FILE_NAME_SPAN = document.getElementById('fileName');

    if (NEWS_INPUT && NEWS_BUTTON) {
        NEWS_BUTTON.disabled = NEWS_INPUT.value.trim().length < 20;
        NEWS_INPUT.addEventListener('input', () => {
            NEWS_BUTTON.disabled = NEWS_INPUT.value.trim().length < 20;
        });
        NEWS_BUTTON.addEventListener('click', checkFakeNews);
    }

    if (DEEPFAKE_INPUT) {
        DEEPFAKE_INPUT.addEventListener('change', handleImageUpload);
    }

    if (DEEPFAKE_BUTTON) {
        DEEPFAKE_BUTTON.disabled = !lastImageFile;
        DEEPFAKE_BUTTON.addEventListener('click', runDeepfakeCheck);
    }
});
