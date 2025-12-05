
import { h, render } from 'preact';
import { useState, useEffect, useCallback, useMemo } from 'preact/hooks';
import htm from 'htm';
import { marked } from 'marked';

const html = htm.bind(h);

marked.setOptions({
    breaks: true,
    gfm: true,
});

// ============================================================================
// Utility Functions
// ============================================================================

function getUnitLabel(payload, unitId, labelField = null) {
    if (!payload) return unitId?.slice(0, 8) || 'Unit';
    if (labelField && payload[labelField] !== undefined) {
        const value = payload[labelField];
        if (typeof value === 'string') {
            if (labelField.toLowerCase().includes('path') || labelField.toLowerCase().includes('file')) {
                return value.split('/').pop();
            }
            return value.slice(0, 60);
        }
        return String(value).slice(0, 60);
    }
    if (payload.file_path) return payload.file_path.split('/').pop();
    if (payload.url) return payload.url.replace(/^https?:\/\//, '').slice(0, 40);
    if (payload.name) return payload.name;
    if (payload.id) return String(payload.id);
    if (payload.title) return payload.title.slice(0, 40);
    const firstString = Object.values(payload).find(v => typeof v === 'string' && v.length < 60);
    if (firstString) return firstString.slice(0, 40);
    return unitId?.slice(0, 8) || 'Unit';
}

function formatTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(seconds) {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}

function timeAgo(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    const seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 5) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function getStatusClass(status) {
    const statusMap = { pending: 'pending', assigned: 'assigned', processing: 'processing', running: 'running', completed: 'completed', failed: 'failed', created: 'pending', ready: 'pending', testing: 'testing', paused: 'assigned', busy: 'busy', idle: 'idle', post_processing: 'post_processing' };
    return statusMap[status] || 'pending';
}

function isPostProcessingUnit(unit) {
    return unit?.unit_type === 'post_processing' || unit?.payload?.type === 'post_processing';
}

function isActiveStatus(status) {
    return ['running', 'created', 'ready', 'testing', 'post_processing'].includes(status);
}

// ============================================================================
// Utility Components
// ============================================================================

function Markdown({ content, className = '' }) {
    if (!content || typeof content !== 'string') return null;
    const htmlContent = marked.parse(content);
    return html`<div class="markdown-content ${className}" dangerouslySetInnerHTML=${{ __html: htmlContent }} />`;
}

function CopyButton({ text, className = '' }) {
    const [copied, setCopied] = useState(false);
    const handleCopy = async (e) => {
        e.stopPropagation();
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };
    return html`<button class="copy-btn ${className}" onClick=${handleCopy} title="Copy to clipboard">${copied ? '✓' : '⎘'}</button>`;
}

function Collapsible({ title, children, defaultOpen = false, className = '' }) {
    const [isOpen, setIsOpen] = useState(defaultOpen);
    return html`
        <div class="collapsible ${className} ${isOpen ? 'open' : ''}">
            <div class="collapsible-header" onClick=${() => setIsOpen(!isOpen)}>
                <span class="collapsible-icon">${isOpen ? '▼' : '▶'}</span>
                <span class="collapsible-title">${title}</span>
            </div>
            ${isOpen && html`<div class="collapsible-content">${children}</div>`}
        </div>
    `;
}

function CollapsibleWithPreview({ title, preview, children, defaultOpen = false, className = '' }) {
    const [isOpen, setIsOpen] = useState(defaultOpen);
    return html`
        <div class="collapsible ${className} ${isOpen ? 'open' : ''}">
            <div class="collapsible-header" onClick=${() => setIsOpen(!isOpen)}>
                <span class="collapsible-icon">${isOpen ? '▼' : '▶'}</span>
                <span class="collapsible-title">${title}</span>
                ${!isOpen && preview && html`<span class="collapsible-preview">${preview}</span>`}
            </div>
            ${isOpen && html`<div class="collapsible-content">${children}</div>`}
        </div>
    `;
}

function Badge({ status, size = 'normal' }) {
    const icons = { pending: '○', assigned: '◐', processing: '●', running: '●', testing: '⧖', completed: '✓', failed: '✗', busy: '●', idle: '○', post_processing: '⚡' };
    const icon = icons[status] || '○';
    const displayStatus = status === 'post_processing' ? 'post-processing' : status;
    return html`<span class="badge badge-${getStatusClass(status)} ${size === 'small' ? 'badge-sm' : ''}">${size !== 'small' && html`<span class="badge-icon">${icon}</span>`}${displayStatus}</span>`;
}

function ProgressBar({ percentage, status, size = 'normal' }) {
    const statusClass = status === 'completed' ? 'completed' : status === 'failed' ? 'failed' : '';
    return html`<div class="progress-bar ${size === 'large' ? 'progress-bar-lg' : ''}"><div class="progress-fill ${statusClass}" style="width: ${percentage}%"></div></div>`;
}

// ============================================================================
// API
// ============================================================================

const api = {
    async getJobs(params = {}) {
        const query = new URLSearchParams(params).toString();
        const res = await fetch(`/api/jobs${query ? '?' + query : ''}`);
        return res.json();
    },
    async getJob(jobId) {
        const res = await fetch(`/api/jobs/${jobId}`);
        return res.json();
    },
    async getJobUnits(jobId, params = {}) {
        const query = new URLSearchParams(params).toString();
        const res = await fetch(`/api/jobs/${jobId}/units${query ? '?' + query : ''}`);
        return res.json();
    },
    async getUnit(jobId, unitId) {
        const res = await fetch(`/api/jobs/${jobId}/units/${unitId}`);
        return res.json();
    },
    async getStats() {
        const res = await fetch('/api/stats');
        return res.json();
    },
    async getJobLogs(jobId, params = {}) {
        const query = new URLSearchParams(params).toString();
        const res = await fetch(`/api/jobs/${jobId}/logs${query ? '?' + query : ''}`);
        return res.json();
    },
    async getJobExecutor(jobId) {
        const res = await fetch(`/api/jobs/${jobId}/executor`);
        return res.json();
    },
    async bypassFailures(jobId) {
        const res = await fetch(`/api/jobs/${jobId}/bypass`, { method: 'POST' });
        return res.json();
    },
    async killJob(jobId) {
        const res = await fetch(`/api/jobs/${jobId}/kill`, { method: 'POST' });
        return res.json();
    },
    async restartJob(jobId) {
        const res = await fetch(`/api/jobs/${jobId}/restart`, { method: 'POST' });
        return res.json();
    },
    async killUnit(jobId, unitId) {
        const res = await fetch(`/api/jobs/${jobId}/units/${unitId}/kill`, { method: 'POST' });
        return res.json();
    },
    async restartUnit(jobId, unitId) {
        const res = await fetch(`/api/jobs/${jobId}/units/${unitId}/restart`, { method: 'POST' });
        return res.json();
    },
    async getJobLiveActivity(jobId) {
        const res = await fetch(`/api/jobs/${jobId}/live`);
        return res.json();
    }
};

// ============================================================================
// Main Dashboard Component - Two Column Layout
// ============================================================================

const JOBS_PAGE_SIZE = 20;

function MissionControl() {
    const [allJobs, setAllJobs] = useState([]);
    const [jobsOffset, setJobsOffset] = useState(0);
    const [hasMoreJobs, setHasMoreJobs] = useState(false);
    const [loadingMoreJobs, setLoadingMoreJobs] = useState(false);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState(null);

    // Selection state: which job is expanded, and what's shown in details panel
    const [expandedJobId, setExpandedJobId] = useState(null);
    const [selectedItem, setSelectedItem] = useState(null); // { type: 'job' | 'unit', job, unit? }

    // Fetch jobs (initial page only, preserves loaded jobs on refresh)
    useEffect(() => {
        async function fetchData() {
            try {
                const jobsData = await api.getJobs({ limit: JOBS_PAGE_SIZE, offset: 0 });
                const jobsList = jobsData.jobs || [];

                // On refresh, update only the first page while preserving any additional loaded jobs
                setAllJobs(prev => {
                    if (prev.length <= JOBS_PAGE_SIZE) {
                        // Only first page loaded, replace entirely
                        setHasMoreJobs(jobsList.length === JOBS_PAGE_SIZE && jobsData.total > JOBS_PAGE_SIZE);
                        return jobsList;
                    }
                    // More pages loaded - merge first page with rest
                    const additionalJobs = prev.slice(JOBS_PAGE_SIZE);
                    const mergedFirstPage = jobsList;
                    return [...mergedFirstPage, ...additionalJobs];
                });
                setLastUpdated(new Date().toISOString());

                // Auto-expand logic: prefer active job, otherwise most recent
                if (jobsList.length > 0 && !expandedJobId) {
                    const activeJob = jobsList.find(j => isActiveStatus(j.status));
                    const jobToExpand = activeJob || jobsList[0];
                    setExpandedJobId(jobToExpand.job_id);
                    setSelectedItem({ type: 'job', job: jobToExpand });
                }

                // If active job started, switch to it
                if (expandedJobId) {
                    const currentExpanded = jobsList.find(j => j.job_id === expandedJobId);
                    const activeJob = jobsList.find(j => isActiveStatus(j.status));
                    if (activeJob && currentExpanded && !isActiveStatus(currentExpanded.status) && activeJob.job_id !== expandedJobId) {
                        setExpandedJobId(activeJob.job_id);
                        setSelectedItem({ type: 'job', job: activeJob });
                    }
                }
            } catch (e) {
                console.error('Failed to fetch jobs:', e);
            } finally {
                setLoading(false);
            }
        }
        fetchData();
        const interval = setInterval(fetchData, 3000);
        return () => clearInterval(interval);
    }, [expandedJobId]);

    // Load more jobs handler
    const loadMoreJobs = async () => {
        if (loadingMoreJobs) return;
        setLoadingMoreJobs(true);
        try {
            const newOffset = jobsOffset + JOBS_PAGE_SIZE;
            const jobsData = await api.getJobs({ limit: JOBS_PAGE_SIZE, offset: newOffset });
            const fetchedJobs = jobsData.jobs || [];
            setAllJobs(prev => [...prev, ...fetchedJobs]);
            setJobsOffset(newOffset);
            setHasMoreJobs(fetchedJobs.length === JOBS_PAGE_SIZE && (newOffset + fetchedJobs.length) < jobsData.total);
        } catch (e) {
            console.error('Failed to load more jobs:', e);
        } finally {
            setLoadingMoreJobs(false);
        }
    };

    // Handle job click - expand and show job details
    const handleJobClick = useCallback((job) => {
        setExpandedJobId(job.job_id);
        setSelectedItem({ type: 'job', job });
    }, []);

    // Handle unit click - show unit details (job stays expanded)
    const handleUnitClick = useCallback((unit, job) => {
        setSelectedItem({ type: 'unit', job, unit });
    }, []);

    if (loading) {
        return html`<div class="dashboard"><div class="loading"><div class="spinner"></div>Loading...</div></div>`;
    }

    const activeJobs = allJobs.filter(j => isActiveStatus(j.status));
    const hasActiveJobs = activeJobs.length > 0;

    return html`
        <div class="dashboard">
            <header class="dashboard-header">
                <h1 class="dashboard-title">Agentic Batch Processor</h1>
                <div class="dashboard-status">
                    <span class="status-dot ${hasActiveJobs ? 'active' : ''}"></span>
                    <span class="status-text">${hasActiveJobs ? `${activeJobs.length} active` : 'Idle'}</span>
                    <span class="status-updated">Updated ${timeAgo(lastUpdated)}</span>
                </div>
            </header>

            <div class="dashboard-content">
                <div class="dashboard-left">
                    ${!hasActiveJobs && html`
                        <div class="no-active-jobs">
                            <div class="no-active-icon">⏸</div>
                            <div class="no-active-text">No active jobs</div>
                            <div class="no-active-subtext">Start a batch job to see it here</div>
                        </div>
                    `}

                    <div class="jobs-list">
                        ${allJobs.map(job => html`
                            <${JobRow}
                                key=${job.job_id}
                                job=${job}
                                isExpanded=${expandedJobId === job.job_id}
                                isActive=${isActiveStatus(job.status)}
                                selectedUnitId=${selectedItem?.type === 'unit' ? selectedItem.unit?.unit_id : null}
                                onJobClick=${() => handleJobClick(job)}
                                onUnitClick=${(unit) => handleUnitClick(unit, job)}
                            />
                        `)}
                        ${hasMoreJobs && html`
                            <button class="show-more-btn" onClick=${loadMoreJobs} disabled=${loadingMoreJobs}>
                                ${loadingMoreJobs ? 'Loading...' : 'Show More Jobs'}
                            </button>
                        `}
                    </div>
                </div>

                <div class="dashboard-right">
                    ${selectedItem ? html`
                        ${selectedItem.type === 'job' ? html`
                            <${JobDetailsPanel} job=${selectedItem.job} />
                        ` : html`
                            <${UnitDetailsPanel} unit=${selectedItem.unit} job=${selectedItem.job} />
                        `}
                    ` : html`
                        <div class="no-selection">
                            <div class="no-selection-text">Select a job or work unit to view details</div>
                        </div>
                    `}
                </div>
            </div>
        </div>
    `;
}

// ============================================================================
// Job Row Component - Expandable job in left column
// ============================================================================

const UNITS_PAGE_SIZE = 20;

function JobRow({ job, isExpanded, isActive, selectedUnitId, onJobClick, onUnitClick }) {
    const [jobData, setJobData] = useState(null);
    const [units, setUnits] = useState([]);
    const [unitsOffset, setUnitsOffset] = useState(0);
    const [hasMoreUnits, setHasMoreUnits] = useState(false);
    const [loadingMoreUnits, setLoadingMoreUnits] = useState(false);
    const [liveActivity, setLiveActivity] = useState([]);
    const [fetchedPostProcessingUnit, setFetchedPostProcessingUnit] = useState(null);
    const labelField = job.metadata?.unit_label_field || null;

    // Fetch detailed job data when expanded or active
    useEffect(() => {
        if (!isExpanded && !isActive) return;

        async function fetchJobData() {
            try {
                const data = await api.getJob(job.job_id);
                setJobData(data);
            } catch (e) {
                console.error('Failed to fetch job data:', e);
            }
        }
        fetchJobData();
        const interval = setInterval(fetchJobData, isActive ? 2000 : 5000);
        return () => clearInterval(interval);
    }, [job.job_id, isExpanded, isActive]);

    // Fetch units when expanded - reset offset when job changes or collapses
    useEffect(() => {
        if (!isExpanded) {
            setUnits([]);
            setUnitsOffset(0);
            setHasMoreUnits(false);
            return;
        }

        async function fetchUnits() {
            try {
                const data = await api.getJobUnits(job.job_id, { limit: UNITS_PAGE_SIZE, offset: 0 });
                const fetchedUnits = data.units || [];
                setUnits(fetchedUnits);
                setUnitsOffset(0);
                setHasMoreUnits(fetchedUnits.length === UNITS_PAGE_SIZE && data.total > UNITS_PAGE_SIZE);
                setFetchedPostProcessingUnit(data.post_processing_unit || null);
            } catch (e) {
                console.error('Failed to fetch units:', e);
            }
        }
        fetchUnits();
        const interval = setInterval(fetchUnits, isActive ? 2000 : 10000);
        return () => clearInterval(interval);
    }, [job.job_id, isExpanded, isActive]);

    // Load more units handler
    const loadMoreUnits = async () => {
        if (loadingMoreUnits) return;
        setLoadingMoreUnits(true);
        try {
            const newOffset = unitsOffset + UNITS_PAGE_SIZE;
            const data = await api.getJobUnits(job.job_id, { limit: UNITS_PAGE_SIZE, offset: newOffset });
            const fetchedUnits = data.units || [];
            setUnits(prev => [...prev, ...fetchedUnits]);
            setUnitsOffset(newOffset);
            setHasMoreUnits(fetchedUnits.length === UNITS_PAGE_SIZE && (newOffset + fetchedUnits.length) < data.total);
            setFetchedPostProcessingUnit(data.post_processing_unit || null);
        } catch (e) {
            console.error('Failed to load more units:', e);
        } finally {
            setLoadingMoreUnits(false);
        }
    };

    // Fetch live activity (latest conversation snippets) for active jobs - poll quickly
    useEffect(() => {
        if (!isActive || !isExpanded) {
            setLiveActivity([]);
            return;
        }

        async function fetchLiveActivity() {
            try {
                const data = await api.getJobLiveActivity(job.job_id);
                setLiveActivity(data.active_units || []);
            } catch (e) {
                console.error('Failed to fetch live activity:', e);
            }
        }
        fetchLiveActivity();
        // Poll every 1 second for live updates
        const interval = setInterval(fetchLiveActivity, 1000);
        return () => clearInterval(interval);
    }, [job.job_id, isActive, isExpanded]);

    const details = jobData?.job || job;
    const recentUnits = jobData?.recent_units || [];
    const unitStats = jobData?.unit_stats || {};

    const total = details.total_units || 1;
    const failed = Math.min(details.failed_units || 0, total);
    // Cap completed at total to handle legacy data where post-processing was counted
    const completed = Math.min(details.completed_units || 0, total);
    const percentage = Math.min(((completed / total) * 100), 100).toFixed(1);
    const processing = (unitStats.processing || 0) + (unitStats.assigned || 0);

    const isTesting = details.status === 'testing';
    const isInPostProcessing = details.status === 'post_processing';
    const postProcessingUnit = fetchedPostProcessingUnit;
    const hasPostProcessing = !!details.post_processing_prompt;

    // Check if test is complete and awaiting user approval
    // Test unit is the first unit, check if it's completed while job is still in testing status
    const testUnit = details.test_unit_id ? recentUnits.find(u => u.unit_id === details.test_unit_id) : null;
    const testComplete = isTesting && testUnit && (testUnit.status === 'completed' || testUnit.status === 'failed');

    // Bypass button logic
    const allUnitsDone = (completed + failed) === total;
    const alreadyBypassed = !!details.bypass_failures;
    const showBypassButton = allUnitsDone && failed > 0 && hasPostProcessing && !alreadyBypassed && details.status === 'failed';

    return html`
        <div class="job-row ${isExpanded ? 'expanded' : ''} ${isActive ? 'active' : ''}">
            <div class="job-row-header" onClick=${onJobClick}>
                <span class="job-row-toggle">${isExpanded ? '▼' : '▶'}</span>
                <span class="job-row-name">${details.name}</span>
                <span class="job-row-progress">${completed}/${total}</span>
                <div class="job-row-bar">
                    <div class="job-row-fill ${details.status}" style="width: ${percentage}%"></div>
                </div>
                <${Badge} status=${details.status} size="small" />
                ${isActive && processing > 0 && html`<span class="job-row-processing">${processing} processing</span>`}
                <span class="job-row-time">${timeAgo(details.completed_at || details.started_at || details.created_at)}</span>
                <${JobControlButtons}
                    jobId=${details.job_id}
                    jobStatus=${details.status}
                    onAction=${() => api.getJob(job.job_id).then(setJobData)}
                />
            </div>

            ${isExpanded && html`
                <div class="job-row-expanded">
                    ${isTesting && !testComplete && html`
                        <div class="job-banner testing">
                            <div class="banner-icon">⧖</div>
                            <div class="banner-content">
                                <div class="banner-title">Test in Progress</div>
                                <div class="banner-subtitle">Running sample to verify configuration...</div>
                            </div>
                            <div class="banner-spinner"><div class="spinner"></div></div>
                        </div>
                    `}

                    ${testComplete && html`
                        <div class="job-banner test-complete ${testUnit?.status === 'completed' ? 'success' : 'failed'}">
                            <div class="banner-icon">${testUnit?.status === 'completed' ? '✓' : '✗'}</div>
                            <div class="banner-content">
                                <div class="banner-title">Test ${testUnit?.status === 'completed' ? 'Passed' : 'Failed'}</div>
                                <div class="banner-subtitle">Return to chat to review results and ${testUnit?.status === 'completed' ? 'approve the run' : 'adjust configuration'}</div>
                            </div>
                            <span class="banner-status ${testUnit?.status}">${testUnit?.status === 'completed' ? '↩' : '↩'}</span>
                        </div>
                    `}

                    ${isInPostProcessing && html`
                        <div class="job-banner post-processing" onClick=${() => postProcessingUnit && onUnitClick(postProcessingUnit)}>
                            <div class="banner-icon">⚡</div>
                            <div class="banner-content">
                                <div class="banner-title">Post-Processing</div>
                                <div class="banner-subtitle">
                                    ${postProcessingUnit?.status === 'completed' ? 'Synthesis complete' :
                                      postProcessingUnit?.status === 'failed' ? 'Synthesis failed' :
                                      'Synthesizing results...'}
                                </div>
                            </div>
                            ${postProcessingUnit?.status === 'processing' && html`<div class="banner-spinner"><div class="spinner"></div></div>`}
                            ${postProcessingUnit?.status === 'completed' && html`<span class="banner-status completed">✓</span>`}
                            ${postProcessingUnit?.status === 'failed' && html`<span class="banner-status failed">✗</span>`}
                        </div>
                    `}

                    ${showBypassButton && html`
                        <${BypassFailuresButton}
                            jobId=${details.job_id}
                            failedCount=${failed}
                            onBypass=${() => api.getJob(job.job_id).then(setJobData)}
                        />
                    `}

                    ${isActive && liveActivity.length > 0 && html`
                        <div class="job-activity">
                            <div class="activity-header">Live Activity</div>
                            ${liveActivity.map((unit, i) => html`
                                <div key=${unit.unit_id} class="activity-item processing" onClick=${(e) => { e.stopPropagation(); onUnitClick({ unit_id: unit.unit_id, payload: unit.payload, status: unit.status }); }}>
                                    <div class="activity-item-header">
                                        <span class="activity-worker">W${i+1}</span>
                                        <span class="activity-icon processing">●</span>
                                        <span class="activity-name">${getUnitLabel(unit.payload, unit.unit_id, labelField)}</span>
                                    </div>
                                    ${unit.latest_event && html`
                                        <div class="activity-snippet">
                                            ${unit.latest_event.type === 'tool_use' ? html`
                                                <span class="snippet-tool">⚙ ${unit.latest_event.tool}</span>
                                            ` : html`
                                                <span class="snippet-text">${unit.latest_event.content}</span>
                                            `}
                                        </div>
                                    `}
                                </div>
                            `)}
                        </div>
                    `}

                    <div class="job-units">
                        ${units.filter(u => !isPostProcessingUnit(u)).map(unit => html`
                            <div key=${unit.unit_id}
                                 class="unit-row ${unit.status} ${selectedUnitId === unit.unit_id ? 'selected' : ''}"
                                 onClick=${(e) => { e.stopPropagation(); onUnitClick(unit); }}>
                                <span class="unit-icon ${unit.status}">
                                    ${unit.status === 'completed' ? '✓' : unit.status === 'failed' ? '✗' : unit.status === 'processing' ? '●' : '○'}
                                </span>
                                <span class="unit-name">${getUnitLabel(unit.payload, unit.unit_id, labelField)}</span>
                                <span class="unit-duration">${formatDuration(unit.execution_time_seconds)}</span>
                            </div>
                        `)}
                        ${hasMoreUnits && html`
                            <button class="show-more-btn" onClick=${(e) => { e.stopPropagation(); loadMoreUnits(); }} disabled=${loadingMoreUnits}>
                                ${loadingMoreUnits ? 'Loading...' : 'Show More Units'}
                            </button>
                        `}
                        ${postProcessingUnit && html`
                            <div key=${postProcessingUnit.unit_id}
                                 class="unit-row post-processing ${postProcessingUnit.status} ${selectedUnitId === postProcessingUnit.unit_id ? 'selected' : ''}"
                                 onClick=${(e) => { e.stopPropagation(); onUnitClick(postProcessingUnit); }}>
                                <span class="unit-icon post-processing">⚡</span>
                                <span class="unit-name">Post-Processing</span>
                                <span class="unit-status ${postProcessingUnit.status}">${postProcessingUnit.status === 'completed' ? '✓' : postProcessingUnit.status === 'failed' ? '✗' : '●'}</span>
                                <span class="unit-duration">${formatDuration(postProcessingUnit.execution_time_seconds)}</span>
                            </div>
                        `}
                        ${units.length === 0 && html`<div class="units-empty">Loading work units...</div>`}
                    </div>
                </div>
            `}
        </div>
    `;
}

// ============================================================================
// Bypass Failures Button
// ============================================================================

function BypassFailuresButton({ jobId, failedCount, onBypass }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const handleBypass = async (e) => {
        e.stopPropagation();
        setLoading(true);
        setError(null);
        try {
            const result = await api.bypassFailures(jobId);
            if (result.error) {
                setError(result.error.message);
            } else if (onBypass) {
                onBypass(result);
            }
        } catch (e) {
            setError('Failed to bypass failures');
        } finally {
            setLoading(false);
        }
    };

    return html`
        <div class="bypass-container">
            <button class="bypass-btn" onClick=${handleBypass} disabled=${loading}>
                ${loading ? '...' : '⚠ Bypass Failures'}
            </button>
            <span class="bypass-text">
                ${failedCount} unit${failedCount !== 1 ? 's' : ''} failed. Bypass to run post-processing anyway.
            </span>
            <span class="bypass-help">
                ?
                <span class="bypass-tooltip">
                    <strong>Bypass Failures</strong><br/>
                    When enabled, post-processing will run even though some work units failed.
                    The failed units will be treated as "ignored" rather than blocking synthesis.
                </span>
            </span>
            ${error && html`<span class="bypass-error">${error}</span>`}
        </div>
    `;
}

// ============================================================================
// Kill/Restart Job Button
// ============================================================================

function JobControlButtons({ jobId, jobStatus, onAction }) {
    const [loading, setLoading] = useState(null); // 'kill' or 'restart'
    const [error, setError] = useState(null);

    const isRunning = ['running', 'testing', 'post_processing'].includes(jobStatus);
    const canRestart = ['failed', 'paused'].includes(jobStatus);

    const handleKill = async (e) => {
        e.stopPropagation();
        if (!confirm('Are you sure you want to kill this job? This will terminate all running workers.')) return;
        setLoading('kill');
        setError(null);
        try {
            const result = await api.killJob(jobId);
            if (result.error) {
                setError(result.error.message);
            } else if (onAction) {
                onAction('killed', result);
            }
        } catch (e) {
            setError('Failed to kill job');
        } finally {
            setLoading(null);
        }
    };

    const handleRestart = async (e) => {
        e.stopPropagation();
        setLoading('restart');
        setError(null);
        try {
            const result = await api.restartJob(jobId);
            if (result.error) {
                setError(result.error.message);
            } else if (onAction) {
                onAction('restarted', result);
            }
        } catch (e) {
            setError('Failed to restart job');
        } finally {
            setLoading(null);
        }
    };

    if (!isRunning && !canRestart) return null;

    return html`
        <div class="job-control-buttons">
            ${isRunning && html`
                <button class="control-btn kill-btn" onClick=${handleKill} disabled=${loading === 'kill'} title="Kill job">
                    ${loading === 'kill' ? '...' : '⏹ Kill'}
                </button>
            `}
            ${canRestart && html`
                <button class="control-btn restart-btn" onClick=${handleRestart} disabled=${loading === 'restart'} title="Restart job">
                    ${loading === 'restart' ? '...' : '↻ Restart'}
                </button>
            `}
            ${error && html`<span class="control-error">${error}</span>`}
        </div>
    `;
}

// ============================================================================
// Kill/Restart Unit Buttons
// ============================================================================

function UnitControlButtons({ jobId, unitId, unitStatus, processId, onAction }) {
    const [loading, setLoading] = useState(null);
    const [error, setError] = useState(null);

    const isProcessing = ['processing', 'assigned'].includes(unitStatus);
    const canKill = isProcessing && processId;
    // Only allow restart for failed units, not completed ones
    const canRestart = unitStatus === 'failed';

    const handleKill = async (e) => {
        e.stopPropagation();
        if (!confirm('Are you sure you want to kill this work unit?')) return;
        setLoading('kill');
        setError(null);
        try {
            const result = await api.killUnit(jobId, unitId);
            if (result.error) {
                setError(result.error.message);
            } else if (onAction) {
                onAction('killed', result);
            }
        } catch (e) {
            setError('Failed to kill unit');
        } finally {
            setLoading(null);
        }
    };

    const handleRestart = async (e) => {
        e.stopPropagation();
        setLoading('restart');
        setError(null);
        try {
            const result = await api.restartUnit(jobId, unitId);
            if (result.error) {
                setError(result.error.message);
            } else if (onAction) {
                onAction('restarted', result);
            }
        } catch (e) {
            setError('Failed to restart unit');
        } finally {
            setLoading(null);
        }
    };

    if (!canKill && !canRestart) return null;

    return html`
        <div class="unit-control-buttons">
            ${canKill && html`
                <button class="control-btn kill-btn" onClick=${handleKill} disabled=${loading === 'kill'} title="Kill this work unit">
                    ${loading === 'kill' ? '...' : '⏹ Kill'}
                </button>
            `}
            ${canRestart && html`
                <button class="control-btn restart-btn" onClick=${handleRestart} disabled=${loading === 'restart'} title="Restart this work unit">
                    ${loading === 'restart' ? '...' : '↻ Restart'}
                </button>
            `}
            ${error && html`<span class="control-error">${error}</span>`}
        </div>
    `;
}

// ============================================================================
// Job Details Panel - Right column when job is selected
// ============================================================================

function JobDetailsPanel({ job }) {
    const [jobData, setJobData] = useState(null);

    useEffect(() => {
        async function fetchJobData() {
            try {
                const data = await api.getJob(job.job_id);
                setJobData(data);
            } catch (e) {
                console.error('Failed to fetch job data:', e);
            }
        }
        fetchJobData();
        const interval = setInterval(fetchJobData, isActiveStatus(job.status) ? 2000 : 10000);
        return () => clearInterval(interval);
    }, [job.job_id, job.status]);

    const details = jobData?.job || job;
    const workers = jobData?.workers || [];
    const unitStats = jobData?.unit_stats || {};
    const recentUnits = jobData?.recent_units || [];

    const total = details.total_units || 1;
    const failed = Math.min(details.failed_units || 0, total);
    // Cap completed at total to handle legacy data where post-processing was counted
    const completed = Math.min(details.completed_units || 0, total);
    const percentage = Math.min(((completed / total) * 100), 100).toFixed(1);
    const processing = (unitStats.processing || 0) + (unitStats.assigned || 0);
    const pending = unitStats.pending || 0;

    // Post-processing status
    const hasPostProcessing = !!details.post_processing_prompt;
    const postProcessingUnit = recentUnits.find(u => isPostProcessingUnit(u));
    const postProcessingStatus = postProcessingUnit?.status;

    return html`
        <div class="details-panel">
            <div class="details-header">
                <h2>${details.name}</h2>
                <${Badge} status=${details.status} />
            </div>

            <div class="details-progress">
                <div class="progress-stats">
                    <span class="progress-count">${completed}<span class="progress-total">/${total}</span></span>
                    <span class="progress-percent">${percentage}%</span>
                    ${hasPostProcessing && html`
                        <span class="progress-post-processing">
                            ${postProcessingStatus === 'completed' ? html`<span class="post-processing-indicator completed">+ ⚡✓</span>` :
                              postProcessingStatus === 'failed' ? html`<span class="post-processing-indicator failed">+ ⚡✗</span>` :
                              postProcessingStatus === 'processing' ? html`<span class="post-processing-indicator processing">+ ⚡...</span>` :
                              html`<span class="post-processing-indicator pending">+ ⚡</span>`}
                        </span>
                    `}
                </div>
                <${ProgressBar} percentage=${parseFloat(percentage)} status=${details.status} size="large" />
            </div>

            <div class="details-stats">
                <div class="stat-pill processing">${processing} processing</div>
                <div class="stat-pill pending">${pending} queued</div>
                <div class="stat-pill completed">${completed} done</div>
                ${failed > 0 && html`<div class="stat-pill failed">${failed} failed</div>`}
            </div>

            ${details.total_cost_usd && html`
                <div class="cost-card">
                    <div class="cost-card-icon">$</div>
                    <div class="cost-card-content">
                        <div class="cost-card-label">Total Cost</div>
                        <div class="cost-card-value">$${details.total_cost_usd.toFixed(4)}</div>
                    </div>
                </div>
            `}

            ${workers.length > 0 && html`
                <div class="details-section">
                    <div class="section-title">Workers</div>
                    <div class="workers-grid">
                        ${workers.map((w, i) => html`
                            <div key=${w.worker_id} class="worker-item ${w.status}">
                                <span class="worker-label">W${i+1}</span>
                                <span class="worker-status ${w.status}">${w.status === 'busy' ? '●' : '○'}</span>
                            </div>
                        `)}
                    </div>
                </div>
            `}

            <div class="details-section">
                <div class="section-title">Configuration</div>
                <div class="config-grid">
                    <div class="config-item">
                        <span class="config-label">Created</span>
                        <span class="config-value">${formatTime(details.created_at)}</span>
                    </div>
                    ${details.started_at && html`
                        <div class="config-item">
                            <span class="config-label">Started</span>
                            <span class="config-value">${formatTime(details.started_at)}</span>
                        </div>
                    `}
                    ${details.completed_at && html`
                        <div class="config-item">
                            <span class="config-label">Completed</span>
                            <span class="config-value">${formatTime(details.completed_at)}</span>
                        </div>
                    `}
                    <div class="config-item">
                        <span class="config-label">Max Workers</span>
                        <span class="config-value">${details.max_workers || '-'}</span>
                    </div>
                </div>
            </div>

            ${details.description && html`
                <${Collapsible} title="Worker Prompt" className="details-section" defaultOpen=${false}>
                    <pre class="prompt-content">${details.description}</pre>
                <//>
            `}

            ${details.post_processing_prompt && html`
                <${Collapsible} title="Post-Processing Prompt" className="details-section" defaultOpen=${false}>
                    <pre class="prompt-content">${details.post_processing_prompt}</pre>
                <//>
            `}
        </div>
    `;
}

// ============================================================================
// Unit Details Panel - Right column when unit is selected
// ============================================================================

function UnitDetailsPanel({ unit, job }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function fetchUnit() {
            try {
                const unitData = await api.getUnit(job.job_id, unit.unit_id);
                setData(unitData);
            } catch (e) {
                console.error('Failed to fetch unit:', e);
            } finally {
                setLoading(false);
            }
        }
        fetchUnit();

        const interval = setInterval(() => {
            if (data?.unit?.status === 'processing' || data?.unit?.status === 'assigned') {
                fetchUnit();
            }
        }, 1000);
        return () => clearInterval(interval);
    }, [job.job_id, unit.unit_id, data?.unit?.status]);

    const unitData = data?.unit || unit;
    const labelField = job.metadata?.unit_label_field || null;
    const unitLabel = getUnitLabel(unitData.payload, unitData.unit_id, labelField);

    // Process conversation
    const processedConversation = useMemo(() => {
        const result = [];
        if (unitData.conversation) {
            for (const msg of unitData.conversation) {
                if (msg.type === 'assistant') {
                    const contentBlocks = msg.message?.content || msg.content || [];
                    if (Array.isArray(contentBlocks)) {
                        let textParts = [];
                        for (const block of contentBlocks) {
                            if (block.type === 'text' && block.text) {
                                textParts.push(block.text);
                            } else if (block.type === 'tool_use') {
                                if (textParts.length > 0) {
                                    result.push({ type: 'agent_text', content: textParts.join('\n') });
                                    textParts = [];
                                }
                                result.push({ type: 'tool_call', toolUse: block, toolResult: null });
                            }
                        }
                        if (textParts.length > 0) {
                            result.push({ type: 'agent_text', content: textParts.join('\n') });
                        }
                    }
                } else if (msg.type === 'user') {
                    const contentBlocks = msg.message?.content || [];
                    if (Array.isArray(contentBlocks)) {
                        for (const block of contentBlocks) {
                            if (block.type === 'tool_result' && block.tool_use_id) {
                                for (const item of result) {
                                    if (item.type === 'tool_call' && item.toolUse?.id === block.tool_use_id) {
                                        item.toolResult = block;
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return result;
    }, [unitData.conversation]);

    return html`
        <div class="details-panel">
            <div class="details-header">
                <h2>${unitLabel}</h2>
                <${Badge} status=${unitData.status} />
            </div>

            ${loading ? html`
                <div class="details-loading"><div class="spinner"></div></div>
            ` : html`
                <${UnitControlButtons}
                    jobId=${job.job_id}
                    unitId=${unitData.unit_id}
                    unitStatus=${unitData.status}
                    processId=${unitData.process_id}
                    onAction=${() => api.getUnit(job.job_id, unit.unit_id).then(setData)}
                />

                ${unitData.error && html`
                    <div class="details-error">
                        <span class="error-icon">✗</span>
                        <span class="error-text">${unitData.error}</span>
                    </div>
                `}

                <div class="details-meta">
                    <div class="meta-item">
                        <span class="meta-label">Duration</span>
                        <span class="meta-value">${formatDuration(unitData.execution_time_seconds)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Retries</span>
                        <span class="meta-value">${unitData.retry_count || 0}</span>
                    </div>
                    ${unitData.cost_usd && html`
                        <div class="meta-item">
                            <span class="meta-label">Cost</span>
                            <span class="meta-value">$${unitData.cost_usd.toFixed(4)}</span>
                        </div>
                    `}
                </div>

                ${unitData.payload && Object.keys(unitData.payload).length > 0 && html`
                    <${Collapsible} title="Payload" className="details-section" defaultOpen=${true}>
                        <div class="payload-grid">
                            ${Object.entries(unitData.payload).map(([key, value]) => {
                                const displayValue = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
                                return html`
                                    <div key=${key} class="payload-item">
                                        <span class="payload-key">${key.toUpperCase()}</span>
                                        <pre class="payload-value">${displayValue}</pre>
                                    </div>
                                `;
                            })}
                        </div>
                    <//>
                `}

                ${unitData.rendered_prompt && html`
                    <${Collapsible} title="Prompt" className="details-section">
                        <div class="prompt-wrapper">
                            <${CopyButton} text=${unitData.rendered_prompt} className="prompt-copy-btn" />
                            <pre class="prompt-content">${unitData.rendered_prompt}</pre>
                        </div>
                    <//>
                `}

                <div class="conversation-section">
                    <div class="conversation-header">Agent Conversation</div>
                    ${processedConversation.length > 0 ? html`
                        <div class="conversation-flow">
                            ${processedConversation.map((item, i) => {
                                if (item.type === 'agent_text') {
                                    return html`
                                        <div key=${i} class="conv-message">
                                            <${Markdown} content=${item.content} />
                                        </div>
                                    `;
                                } else if (item.type === 'tool_call') {
                                    return html`<${ToolCallBlock} key=${i} toolUse=${item.toolUse} toolResult=${item.toolResult} />`;
                                }
                                return null;
                            })}
                        </div>
                    ` : html`
                        <div class="conversation-empty">
                            ${unitData.status === 'processing' || unitData.status === 'assigned' ? html`
                                <div class="spinner"></div>
                                <span>Agent is working...</span>
                            ` : unitData.status === 'pending' ? html`
                                <span>Waiting for worker...</span>
                            ` : html`
                                <span>No conversation data</span>
                            `}
                        </div>
                    `}
                </div>
            `}
        </div>
    `;
}

// ============================================================================
// Tool Call Block
// ============================================================================

function ToolCallBlock({ toolUse, toolResult }) {
    const toolName = toolUse?.name || toolUse?.tool || 'Unknown Tool';
    const toolInput = toolUse?.input || toolUse?.tool_input || {};
    const inputStr = JSON.stringify(toolInput, null, 2);
    const inputPreview = JSON.stringify(toolInput).replace(/\s+/g, ' ');

    let resultContent = '';
    if (toolResult) {
        const content = toolResult.content || toolResult.output || toolResult.result || '';
        if (Array.isArray(content)) {
            resultContent = content.map(item => {
                if (item.type === 'text') return item.text;
                if (item.type === 'image') return '[Image data]';
                return '';
            }).filter(p => p).join('\n');
        } else {
            resultContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
        }
    }
    const outputPreview = resultContent.replace(/\s+/g, ' ');

    return html`
        <div class="tool-block">
            <div class="tool-header">
                <span class="tool-icon">⚙</span>
                <span class="tool-name">${toolName}</span>
            </div>
            <${CollapsibleWithPreview} title="Input" preview=${inputPreview} defaultOpen=${false} className="tool-section">
                <pre class="tool-code">${inputStr}</pre>
            <//>
            ${resultContent && html`
                <${CollapsibleWithPreview} title="Output" preview=${outputPreview} defaultOpen=${false} className="tool-section">
                    <div class="tool-output-wrapper">
                        <${CopyButton} text=${resultContent} className="tool-copy" />
                        <pre class="tool-code">${resultContent}</pre>
                    </div>
                <//>
            `}
        </div>
    `;
}

// ============================================================================
// App Entry Point
// ============================================================================

function App() {
    return html`<${MissionControl} />`;
}

render(html`<${App} />`, document.getElementById('app'));
