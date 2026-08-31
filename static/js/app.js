document.addEventListener("DOMContentLoaded", () => {
    // --- SOURCES MODAL ---
    const sourcesModal = document.getElementById('sourcesModal');
    const closeModalBtn = document.getElementById('closeSourcesModal');
    const modalBackdrop = document.getElementById('sourcesModalBackdrop');

    function openSourcesModal() {
        sourcesModal.classList.add('modal-open');
        document.body.style.overflow = 'hidden';
    }

    function closeSourcesModal() {
        sourcesModal.classList.remove('modal-open');
        document.body.style.overflow = '';
    }

    document.getElementById('openSourcesModal').addEventListener('click', (e) => {
        e.preventDefault();
        openSourcesModal();
    });

    document.getElementById('openSourcesModalFooter').addEventListener('click', openSourcesModal);
    closeModalBtn.addEventListener('click', closeSourcesModal);
    modalBackdrop.addEventListener('click', closeSourcesModal);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sourcesModal.classList.contains('modal-open')) {
            closeSourcesModal();
        }
    });

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

    // --- FLARE RISK CLASSIFICATION (matches NASA DONKI class scale: A < B < C < M < X) ---
    const FLARE_RISK_BY_CLASS = {
        A: { level: "low", label: "Low" },
        B: { level: "low", label: "Low" },
        C: { level: "moderate", label: "Moderate" },
        M: { level: "high", label: "High" },
        X: { level: "critical", label: "Critical" }
    };

    function classifyFlareRisk(classType) {
        if (!classType) return null;
        const letter = classType.trim().charAt(0).toUpperCase();
        return FLARE_RISK_BY_CLASS[letter] || null;
    }

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

    // Geolocation (real, via browser API)
    btnLocation.addEventListener('click', () => {
        if (!('geolocation' in navigator)) {
            locationText.textContent = "Geolocation not supported";
            return;
        }

        locationText.textContent = "Getting location...";
        btnLocation.classList.add('animate-pulse');
        btnLocation.disabled = true;

        navigator.geolocation.getCurrentPosition(
            (position) => {
                userLocation = {
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude
                };
                locationText.textContent = "📍 Location detected";
                btnLocation.classList.remove('animate-pulse');
                btnLocation.classList.remove('text-slate-400');
                // Adding cosmic purple styles for the active state
                btnLocation.classList.add('text-cosmic-400', 'bg-cosmic-900/30', 'border', 'border-cosmic-500/30');
                btnLocation.disabled = false;
            },
            (error) => {
                btnLocation.classList.remove('animate-pulse');
                btnLocation.disabled = false;
                const messages = {
                    1: "Location access denied",
                    2: "Location unavailable",
                    3: "Location request timed out"
                };
                locationText.textContent = messages[error.code] || "Could not get location";
            },
            { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 }
        );
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
            const rawBody = await response.text();

            let payload;
            try {
                payload = rawBody ? JSON.parse(rawBody) : {};
            } catch (parseError) {
                // The server didn't return JSON (e.g. an unhandled crash returning
                // a plain-text/HTML error page). Surface the raw body so it's
                // debuggable instead of a cryptic "unexpected character" message.
                throw new Error(
                    `The server returned a non-JSON response (status ${response.status}): ` +
                    rawBody.slice(0, 200)
                );
            }

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

            renderResults(buildResultViewModel(payload, domainLabels));
        } catch (error) {
            showError(error.message || "The ASTRA API is currently unavailable.");
        }
    }

    function buildResultViewModel(payload, domainLabels) {
        const title = domainLabels[payload.intent.domain] || domainLabels.unknown;
        const toolResult = payload.tool_result;

        // Default (generic) metadata — used when watsonx answered without calling a tool,
        // or when watsonx.ai isn't configured on the server yet.
        let data = [
            { label: "Status", value: payload.status },
            { label: "Detected domain", value: payload.intent.domain },
            { label: "Tool used", value: payload.tool_used || payload.intent.suggested_tool || "None" },
            { label: "Request ID", value: payload.request_id }
        ];
        let sources = payload.tool_used ? ["IBM watsonx"] : ["ASTRA API"];
        let risk = null;

        // Richer view when the space-weather tool actually ran (get_space_weather -> NASA DONKI)
        if (payload.tool_used === "get_space_weather" && toolResult) {
            data = [
                { label: "Period queried", value: `${toolResult.query_start} → ${toolResult.query_end}` },
                { label: "Flares observed", value: String(toolResult.event_count) },
                { label: "Strongest class", value: toolResult.strongest_class || "None detected" },
                { label: "Source", value: toolResult.source }
            ];
            sources = ["IBM watsonx", toolResult.source];
            risk = classifyFlareRisk(toolResult.strongest_class);
        }

        // Richer view when the comet tool actually ran (get_visible_comets -> NASA/JPL SBDB CAD API)
        if (payload.tool_used === "get_visible_comets" && toolResult) {
            data = [
                { label: "Period queried", value: `${toolResult.query_start} → ${toolResult.query_end}` },
                { label: "Close approaches", value: String(toolResult.event_count) },
                { label: "Closest distance", value: toolResult.closest_distance_au != null ? `${toolResult.closest_distance_au} AU` : "None detected" },
                { label: "Source", value: toolResult.source }
            ];
            sources = ["IBM watsonx", toolResult.source];
        }

        // Richer view when the asteroid tool actually ran (get_near_earth_objects -> NASA NeoWs)
        if (payload.tool_used === "get_near_earth_objects" && toolResult) {
            const closestKm = toolResult.closest_miss_km != null
                ? `${Number(toolResult.closest_miss_km).toLocaleString('en-US', {maximumFractionDigits: 0})} km`
                : "None detected";
            data = [
                { label: "Period queried", value: `${toolResult.query_start} → ${toolResult.query_end}` },
                { label: "Asteroids found", value: String(toolResult.event_count) },
                { label: "Potentially hazardous", value: String(toolResult.hazardous_count) },
                { label: "Closest miss", value: closestKm },
            ];
            sources = ["IBM watsonx", toolResult.source];
            // Show risk badge if any potentially hazardous object is in the window
            if (toolResult.hazardous_count > 0) {
                risk = { level: "high", label: "PHAs Detected" };
            }
        }

        return {
            title,
            answer: payload.answer,
            category: payload.intent.domain,
            risk,
            data,
            sources,
            updated_at: payload.received_at
        };
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
        const rawHtml = marked.parse(data.answer || '');
        resultAnswer.innerHTML = (typeof DOMPurify !== 'undefined')
            ? DOMPurify.sanitize(rawHtml)
            : rawHtml;

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