
import { h } from 'preact';
import { useRef, useEffect, useState } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

class Particle {
    constructor(id, status, x, y) {
        this.id = id;
        this.status = status;
        this.x = x;
        this.y = y;
        this.targetX = x;
        this.targetY = y;
        this.vx = 0;
        this.vy = 0;
        this.radius = 6;
        this.alpha = 1;
        this.pulsePhase = Math.random() * Math.PI * 2;
    }

    update(dt) {

        const dx = this.targetX - this.x;
        const dy = this.targetY - this.y;
        this.x += dx * 0.1;
        this.y += dy * 0.1;

        if (this.status === 'processing') {
            this.pulsePhase += dt * 4;
        }

        if (this.status === 'completed' || this.status === 'failed') {
            this.alpha = Math.max(0, this.alpha - dt * 0.5);
        }
    }

    draw(ctx) {
        ctx.save();
        ctx.globalAlpha = this.alpha;

        ctx.beginPath();
        let radius = this.radius;

        if (this.status === 'processing') {
            radius += Math.sin(this.pulsePhase) * 2;
        }

        ctx.arc(this.x, this.y, radius, 0, Math.PI * 2);

        const colors = {
            pending: '#71717a',
            processing: '#3b82f6',
            completed: '#22c55e',
            failed: '#ef4444'
        };
        ctx.fillStyle = colors[this.status] || colors.pending;
        ctx.fill();

        if (this.status === 'processing') {
            ctx.shadowColor = '#3b82f6';
            ctx.shadowBlur = 10;
            ctx.fill();
        }

        ctx.restore();
    }
}

class WorkerNode {
    constructor(id, x, y) {
        this.id = id;
        this.x = x;
        this.y = y;
        this.width = 80;
        this.height = 50;
        this.status = 'idle';
        this.flashTimer = 0;
        this.unitsCompleted = 0;
    }

    update(dt) {
        if (this.flashTimer > 0) {
            this.flashTimer -= dt;
            if (this.flashTimer <= 0) {
                this.status = 'idle';
            }
        }
    }

    flash(success = true) {
        this.status = 'flash';
        this.flashTimer = 0.3;
        this.flashColor = success ? '#22c55e' : '#ef4444';
    }

    draw(ctx) {
        ctx.save();

        ctx.fillStyle = '#1a1d24';
        ctx.strokeStyle = this.status === 'busy' ? '#3b82f6' :
                         this.status === 'flash' ? this.flashColor : '#3f3f46';
        ctx.lineWidth = 2;

        const rx = this.x - this.width / 2;
        const ry = this.y - this.height / 2;
        const r = 6;

        ctx.beginPath();
        ctx.moveTo(rx + r, ry);
        ctx.lineTo(rx + this.width - r, ry);
        ctx.quadraticCurveTo(rx + this.width, ry, rx + this.width, ry + r);
        ctx.lineTo(rx + this.width, ry + this.height - r);
        ctx.quadraticCurveTo(rx + this.width, ry + this.height, rx + this.width - r, ry + this.height);
        ctx.lineTo(rx + r, ry + this.height);
        ctx.quadraticCurveTo(rx, ry + this.height, rx, ry + this.height - r);
        ctx.lineTo(rx, ry + r);
        ctx.quadraticCurveTo(rx, ry, rx + r, ry);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = '#a1a1aa';
        ctx.font = '11px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`W${this.id}`, this.x, this.y - 5);

        ctx.fillStyle = '#71717a';
        ctx.font = '10px Inter, sans-serif';
        ctx.fillText(`${this.unitsCompleted} done`, this.x, this.y + 10);

        ctx.restore();
    }
}

class WorkerVisualization {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.workers = [];
        this.particles = [];
        this.pendingQueue = [];
        this.completedPile = [];
        this.lastTime = performance.now();
        this.running = true;

        this.queueX = 60;
        this.workersY = canvas.height / 2;
        this.completedX = canvas.width - 60;
    }

    setWorkerCount(count) {
        this.workers = [];
        const spacing = (this.canvas.width - 200) / (count + 1);
        for (let i = 0; i < count; i++) {
            this.workers.push(new WorkerNode(
                i + 1,
                100 + spacing * (i + 1),
                this.workersY
            ));
        }
    }

    updateStats(stats) {

        const pendingCount = Math.min(stats.pending || 0, 50);
        while (this.pendingQueue.length < pendingCount) {
            const y = this.workersY - 60 + Math.random() * 120;
            this.pendingQueue.push(new Particle(
                `pending-${Date.now()}-${Math.random()}`,
                'pending',
                this.queueX + Math.random() * 30,
                y
            ));
        }
        while (this.pendingQueue.length > pendingCount) {
            this.pendingQueue.pop();
        }
    }

    updateWorkers(workers) {
        workers.forEach((w, i) => {
            if (this.workers[i]) {
                const wasIdle = this.workers[i].status === 'idle';
                this.workers[i].status = w.status === 'busy' ? 'busy' : 'idle';
                this.workers[i].unitsCompleted = w.units_completed || 0;

                if (w.status === 'busy' && wasIdle) {
                    this.addProcessingParticle(i);
                }
            }
        });
    }

    addProcessingParticle(workerIndex) {
        if (this.workers[workerIndex]) {
            const worker = this.workers[workerIndex];
            const particle = new Particle(
                `proc-${Date.now()}`,
                'processing',
                worker.x,
                worker.y + 40
            );
            this.particles.push(particle);
        }
    }

    onUnitCompleted(workerIndex, success = true) {
        if (this.workers[workerIndex]) {
            this.workers[workerIndex].flash(success);

            const particle = new Particle(
                `done-${Date.now()}`,
                success ? 'completed' : 'failed',
                this.workers[workerIndex].x,
                this.workers[workerIndex].y + 40
            );
            particle.targetX = this.completedX;
            particle.targetY = this.workersY;
            this.particles.push(particle);
        }
    }

    render() {
        if (!this.running) return;

        const now = performance.now();
        const dt = (now - this.lastTime) / 1000;
        this.lastTime = now;

        this.ctx.fillStyle = '#0f1117';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        this.ctx.fillStyle = '#71717a';
        this.ctx.font = '10px Inter, sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('QUEUE', this.queueX, 20);

        this.ctx.fillText('DONE', this.completedX, 20);

        this.pendingQueue.forEach(p => {
            p.update(dt);
            p.draw(this.ctx);
        });

        this.workers.forEach(w => {
            w.update(dt);
            w.draw(this.ctx);
        });

        this.particles = this.particles.filter(p => p.alpha > 0);
        this.particles.forEach(p => {
            p.update(dt);
            p.draw(this.ctx);
        });

        this.ctx.strokeStyle = '#27272a';
        this.ctx.setLineDash([5, 5]);
        this.ctx.beginPath();
        this.ctx.moveTo(this.queueX + 40, this.workersY);
        this.ctx.lineTo(80, this.workersY);
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.moveTo(this.canvas.width - 100, this.workersY);
        this.ctx.lineTo(this.completedX - 20, this.workersY);
        this.ctx.stroke();
        this.ctx.setLineDash([]);

        requestAnimationFrame(() => this.render());
    }

    start() {
        this.running = true;
        this.render();
    }

    stop() {
        this.running = false;
    }
}

export function LiveWorkerViz({ workers = [], stats = {}, onReady }) {
    const canvasRef = useRef(null);
    const vizRef = useRef(null);

    useEffect(() => {
        if (canvasRef.current && !vizRef.current) {
            const canvas = canvasRef.current;
            canvas.width = canvas.offsetWidth;
            canvas.height = 200;

            vizRef.current = new WorkerVisualization(canvas);
            vizRef.current.setWorkerCount(workers.length || 4);
            vizRef.current.start();

            if (onReady) onReady(vizRef.current);
        }

        return () => {
            if (vizRef.current) {
                vizRef.current.stop();
            }
        };
    }, []);

    useEffect(() => {
        if (vizRef.current) {
            vizRef.current.setWorkerCount(workers.length || 4);
            vizRef.current.updateWorkers(workers);
            vizRef.current.updateStats(stats);
        }
    }, [workers, stats]);

    return html`
        <div class="card" style="margin-bottom: var(--space-6)">
            <h3 class="card-title">Live Worker Visualization</h3>
            <canvas ref=${canvasRef} style="width: 100%; height: 200px; border-radius: var(--radius-md);"></canvas>
            <div style="display: flex; gap: var(--space-4); justify-content: center; margin-top: var(--space-3); font-size: 0.75rem; color: var(--text-muted)">
                <span><span style="color: var(--status-pending)">●</span> Pending</span>
                <span><span style="color: var(--status-processing)">●</span> Processing</span>
                <span><span style="color: var(--status-completed)">●</span> Completed</span>
                <span><span style="color: var(--status-failed)">●</span> Failed</span>
            </div>
        </div>
    `;
}

export default LiveWorkerViz;
