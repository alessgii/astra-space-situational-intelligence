document.addEventListener("DOMContentLoaded", () => {
    // --- DOM ELEMENTS ---
    const queryInput = document.getElementById('query-input');
    const btnSubmit = document.getElementById('btn-submit');
    const btnLocation = document.getElementById('btn-location');
    const locationText = document.getElementById('location-text');
    const quickQueries = document.querySelectorAll('.quick-query');
    
    // View sections
    const initialState = document.getElementById('initial-state');
    const processingState = document.getElementById('processing-state');
    const resultsState = document.getElementById('results-state');
    const errorState = document.getElementById('error-state');
    const processingSteps = document.getElementById('processing-steps');

    // Result elements
    const resultTitle = document.getElementById('result-title');
    const resultAnswer = document.getElementById('result-answer');
    const riskBadge = document.getElementById('risk-badge');
    const dataGrid = document.getElementById('data-grid');
    const sourcesList = document.getElementById('sources-list');
    const updateTime = document.getElementById('update-time');
    const btnRetry = document.getElementById('btn-retry');

    // --- GLOBAL STATE ---
    let userLocation = { latitude: null, longitude: null };

    // --- MOCK RESPONSES (To be replaced with your FastAPI backend) ---
    const MOCK_API = {
        solar: {
            title: "Moderate Solar Activity",
            answer: "Over the next few days, moderate solar activity is expected. Current data does not indicate a widespread disruption of telecommunications, although certain high-frequency radio systems and satellite communications could experience minor interference during intense events.",
            category: "space_weather",
            risk: { level: "moderate", label: "Moderate" },
            data: [
                { label: "Latest Activity", value: "Class X1.2 Flare" },
                { label: "Geomagnetic Index", value: "G2 (Moderate)" },
                { label: "Sunspots (AR)", value: "3 Active Regions" },
                { label: "Solar Wind Speed", value: "540 km/s" }
            ],
            sources: ["NOAA", "NASA SDO"],
            updated_at: new Date().toISOString()
        },
        asteroid: {
            title: "No Imminent Impact Risk",
            answer: "This week, asteroid 2026 AB12 will have a close approach to Earth, passing safely at about 2.7 million kilometers (approximately 7 times the distance to the Moon). It poses no impact danger, although it is classified as a Potentially Hazardous Asteroid (PHA) due to its size.",
            category: "nea",
            risk: { level: "low", label: "Low" },
            data: [
                { label: "Designation", value: "2026 AB12" },
                { label: "Approach Date", value: "Aug 24, 2026" },
                { label: "Miss Distance", value: "0.018 AU" },
                { label: "Est. Diameter", value: "80 – 180 m" }
            ],
            sources: ["CNEOS NASA", "JPL Horizons"],
            updated_at: new Date().toISOString()
        },
        comet: {
            title: "Comet C/2026 X1 Visible with Binoculars",
            answer: "From your current location, comet C/2026 X1 will be observable just before dawn by looking East. It currently has a magnitude of 5.8, meaning it will be visible using standard binoculars if you move away from city light pollution.",
            category: "comets",
            risk: null, // No risk associated
            data: [
                { label: "Designation", value: "C/2026 X1" },
                { label: "Est. Magnitude", value: "5.8" },
                { label: "Best Time", value: "04:30 AM (Local)" },
                { label: "Direction", value: "East (Elevation 15°)" }
            ],
            sources: ["Minor Planet Center", "OpenAstronomy"],
            updated_at: new Date().toISOString()
        }
    };

    // --- EVENT LISTENERS ---

    // Auto-expand textarea
    queryInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });

    // Submit with Enter (without Shift)
    queryInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleQuerySubmit();
        }
    });

    btnSubmit.addEventListener('click', handleQuerySubmit);
    
    btnRetry.addEventListener('click', () => { 
        hideAllSections(); 
        initialState.classList.remove('hidden'); 
        queryInput.focus(); 
    });

    // Quick Queries Buttons
    quickQueries.forEach(btn => {
        btn.addEventListener('click', () => {
            queryInput.value = btn.getAttribute('data-query');
            queryInput.dispatchEvent(new Event('input')); // trigger auto-resize
            queryInput.focus();
        });
    });

    // Geolocation (Simulated/Optional)
    btnLocation.addEventListener('click', () => {
        locationText.textContent = "Getting location...";
        btnLocation.classList.add('animate-pulse');
        
        // Simulate geolocation API delay
        setTimeout(() => {
            userLocation = { latitude: 19.0, longitude: -103.7 };
            locationText.textContent = "📍 Location detected";
            btnLocation.classList.remove('animate-pulse');
            btnLocation.classList.remove('text-slate-400');
            // Adding cosmic purple styles for the active state
            btnLocation.classList.add('text-cosmic-400', 'bg-cosmic-900/30', 'border', 'border-cosmic-500/30');
        }, 1200);
    });

    // --- PROCESSING LOGIC ---
    
    function hideAllSections() {
        initialState.classList.add('hidden');
        processingState.classList.add('hidden');
        processingState.classList.remove('flex');
        resultsState.classList.add('hidden');
        resultsState.classList.remove('flex');
        errorState.classList.add('hidden');
    }

    async function handleQuerySubmit() {
        const query = queryInput.value.trim();
        if (!query) return;

        hideAllSections();
        processingState.classList.remove('hidden');
        processingState.classList.add('flex', 'fade-in');
        
        const apiRequest = fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: query,
                location: userLocation.latitude !== null ? userLocation : null
            })
        });

        await showProcessingSteps([
            "Analyzing natural language...",
            "Sending query to the ASTRA API..."
        ]);

        try {
            const response = await apiRequest;
            const payload = await response.json();

            if (!response.ok) {
                const detail = Array.isArray(payload.detail)
                    ? payload.detail.map(item => item.msg).join(' · ')
                    : payload.detail;
                throw new Error(detail || `API error (${response.status})`);
            }

            const domainLabels = {
                space_weather: "Space weather query received",
                near_earth_objects: "Near-Earth object query received",
                comets: "Comet observation query received",
                unknown: "Space query received"
            };

            renderResults({
                title: domainLabels[payload.intent.domain] || domainLabels.unknown,
                answer: payload.answer,
                category: payload.intent.domain,
                risk: null,
                data: [
                    { label: "Status", value: payload.status },
                    { label: "Detected domain", value: payload.intent.domain },
                    { label: "Tool used", value: payload.tool_used || payload.intent.suggested_tool || "None" },
                    { label: "Request ID", value: payload.request_id }
                ],
                sources: payload.tool_used ? ["IBM watsonx", "NASA DONKI"] : ["ASTRA API"],
                updated_at: payload.received_at
            });
        } catch (error) {
            showError(error.message || "The ASTRA API is currently unavailable.");
        }
    }

    function showProcessingSteps(steps) {
        return new Promise(resolve => {
            processingSteps.innerHTML = '';
            let currentStep = 0;

            const interval = setInterval(() => {
                if (currentStep < steps.length) {
                    // Added typing-pulse class that uses the cosmic-400 color defined in CSS
                    processingSteps.innerHTML = `<span class="typing-pulse font-medium">${steps[currentStep]}</span>`;
                    currentStep++;
                } else {
                    clearInterval(interval);
                    resolve();
                }
            }, 800); // 800ms per simulated state
        });
    }

    function renderResults(data) {
        hideAllSections();
        resultsState.classList.remove('hidden');
        resultsState.classList.add('flex', 'fade-in');

        // 1. Agent Response
        resultTitle.textContent = data.title;
        resultAnswer.textContent = data.answer;

        // 2. Risk Badge
        if (data.risk) {
            riskBadge.classList.remove('hidden');
            riskBadge.textContent = data.risk.label;
            
            // Clean previous classes
            riskBadge.className = 'px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border shadow-sm';
            
            // Assign colors based on risk level
            const riskColors = {
                'low': 'bg-green-950/60 text-green-400 border-green-800/80',
                'moderate': 'bg-yellow-950/60 text-yellow-400 border-yellow-800/80',
                'high': 'bg-orange-950/60 text-orange-400 border-orange-800/80',
                'critical': 'bg-red-950/60 text-red-400 border-red-800/80'
            };
            riskBadge.classList.add(...(riskColors[data.risk.level]).split(' '));
        } else {
            riskBadge.classList.add('hidden');
        }

        // 3. Scientific Data Grid
        dataGrid.innerHTML = '';
        data.data.forEach(item => {
            const card = document.createElement('div');
            // Adding cosmic hover effects to data cards
            card.className = 'bg-space-900/60 backdrop-blur border border-space-700/50 hover:border-cosmic-500/30 rounded-xl p-4 flex flex-col justify-center transition-all shadow-[0_4px_20px_rgba(0,0,0,0.3)]';
            card.innerHTML = `
                <span class="text-xs text-slate-500 uppercase tracking-wider mb-1">${item.label}</span>
                <span class="text-sm font-mono text-white font-medium">${item.value}</span>
            `;
            dataGrid.appendChild(card);
        });

        // 4. Sources & Metadata
        sourcesList.innerHTML = '';
        data.sources.forEach(source => {
            const span = document.createElement('span');
            span.className = 'bg-space-800/80 border border-space-700 px-2 py-1 rounded text-slate-300 shadow-sm';
            span.textContent = source;
            sourcesList.appendChild(span);
        });

        const date = new Date(data.updated_at);
        // Formateado al estilo US (inglés)
        updateTime.textContent = `Updated: ${date.toLocaleDateString('en-US')} · ${date.toLocaleTimeString('en-US', {hour: '2-digit', minute:'2-digit'})}`;
    }

    function showError(message) {
        hideAllSections();
        errorState.classList.remove('hidden');
        errorState.classList.add('fade-in');
        document.getElementById('error-message').textContent = message;
    }
});
