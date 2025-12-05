
import { h } from 'preact';
import { useRef, useEffect, useState } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

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

class TimelineVisualization {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.data = { workers: [], units: [] };

        this.margin = { top: 30, right: 20, bottom: 30, left: 60 };
        this.rowHeight = 30;
        this.barHeight = 20;

        this.startTime = null;
        this.endTime = null;

        this.hoveredUnit = null;
        this.onClick = null;
        this.labelField = null;

        this.setupEvents();
    }

    setupEvents() {
        this.canvas.addEventListener('mousemove', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            this.handleMouseMove(x, y);
        });

        this.canvas.addEventListener('click', (e) => {
            if (this.hoveredUnit && this.onClick) {
                this.onClick(this.hoveredUnit);
            }
        });

        this.canvas.addEventListener('mouseleave', () => {
            this.hoveredUnit = null;
            this.render();
        });
    }

    handleMouseMove(x, y) {
        let found = null;

        for (const unit of this.data.units) {
            if (x >= unit.renderX && x <= unit.renderX + unit.renderWidth &&
                y >= unit.renderY && y <= unit.renderY + this.barHeight) {
                found = unit;
                break;
            }
        }

        if (found !== this.hoveredUnit) {
            this.hoveredUnit = found;
            this.canvas.style.cursor = found ? 'pointer' : 'default';
            this.render();
        }
    }

    setData(workers, units) {
        this.data = { workers, units };

        let minTime = Infinity;
        let maxTime = -Infinity;

        units.forEach(unit => {
            if (unit.started_at) {
                const start = new Date(unit.started_at).getTime();
                minTime = Math.min(minTime, start);

                if (unit.completed_at) {
                    const end = new Date(unit.completed_at).getTime();
                    maxTime = Math.max(maxTime, end);
                } else {
                    maxTime = Math.max(maxTime, Date.now());
                }
            }
        });

        if (minTime !== Infinity) {
            this.startTime = minTime;
            this.endTime = maxTime || Date.now();
        }

        this.render();
    }

    timeToX(time) {
        if (!this.startTime || !this.endTime) return 0;
        const width = this.canvas.width - this.margin.left - this.margin.right;
        const range = this.endTime - this.startTime;
        if (range === 0) return this.margin.left;
        return this.margin.left + ((time - this.startTime) / range) * width;
    }

    render() {
        const { ctx, canvas } = this;
        const width = canvas.width;
        const height = canvas.height;

        ctx.fillStyle = '#1a1d24';
        ctx.fillRect(0, 0, width, height);

        if (!this.startTime || this.data.workers.length === 0) {
            ctx.fillStyle = '#71717a';
            ctx.font = '12px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No timeline data available', width / 2, height / 2);
            return;
        }

        this.drawTimeAxis();

        this.drawWorkerLanes();

        this.drawUnits();

        if (this.hoveredUnit) {
            this.drawTooltip();
        }
    }

    drawTimeAxis() {
        const { ctx, canvas, margin } = this;
        const width = canvas.width - margin.left - margin.right;

        ctx.strokeStyle = '#3f3f46';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(margin.left, margin.top);
        ctx.lineTo(canvas.width - margin.right, margin.top);
        ctx.stroke();

        const range = this.endTime - this.startTime;
        const tickCount = 5;
        ctx.fillStyle = '#71717a';
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center';

        for (let i = 0; i <= tickCount; i++) {
            const time = this.startTime + (range * i / tickCount);
            const x = this.timeToX(time);
            const date = new Date(time);
            const label = date.toLocaleTimeString('en-US', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });

            ctx.fillText(label, x, margin.top - 8);

            ctx.beginPath();
            ctx.moveTo(x, margin.top);
            ctx.lineTo(x, margin.top + 5);
            ctx.stroke();
        }
    }

    drawWorkerLanes() {
        const { ctx, canvas, margin, rowHeight, data } = this;

        data.workers.forEach((worker, i) => {
            const y = margin.top + i * rowHeight;

            if (i % 2 === 0) {
                ctx.fillStyle = '#141619';
                ctx.fillRect(margin.left, y, canvas.width - margin.left - margin.right, rowHeight);
            }

            ctx.fillStyle = '#a1a1aa';
            ctx.font = '11px Inter, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(`W${i + 1}`, margin.left - 8, y + rowHeight / 2 + 4);
        });
    }

    drawUnits() {
        const { ctx, margin, rowHeight, barHeight, data, hoveredUnit } = this;

        const workerUnits = new Map();
        data.workers.forEach((w, i) => workerUnits.set(w.worker_id, i));

        data.units.forEach(unit => {
            if (!unit.started_at) return;

            const workerIndex = workerUnits.get(unit.worker_id);
            if (workerIndex === undefined) return;

            const startTime = new Date(unit.started_at).getTime();
            const endTime = unit.completed_at ?
                new Date(unit.completed_at).getTime() : Date.now();

            const x = this.timeToX(startTime);
            const endX = this.timeToX(endTime);
            const width = Math.max(endX - x, 4);
            const y = margin.top + workerIndex * rowHeight + (rowHeight - barHeight) / 2;

            unit.renderX = x;
            unit.renderY = y;
            unit.renderWidth = width;

            let color;
            if (unit.status === 'completed') {
                color = '#22c55e';
            } else if (unit.status === 'failed') {
                color = '#ef4444';
            } else {
                color = '#3b82f6';
            }

            ctx.fillStyle = color;
            if (unit === hoveredUnit) {
                ctx.fillStyle = color;
                ctx.shadowColor = color;
                ctx.shadowBlur = 8;
            }

            const r = 3;
            ctx.beginPath();
            ctx.moveTo(x + r, y);
            ctx.lineTo(x + width - r, y);
            ctx.quadraticCurveTo(x + width, y, x + width, y + r);
            ctx.lineTo(x + width, y + barHeight - r);
            ctx.quadraticCurveTo(x + width, y + barHeight, x + width - r, y + barHeight);
            ctx.lineTo(x + r, y + barHeight);
            ctx.quadraticCurveTo(x, y + barHeight, x, y + barHeight - r);
            ctx.lineTo(x, y + r);
            ctx.quadraticCurveTo(x, y, x + r, y);
            ctx.closePath();
            ctx.fill();

            ctx.shadowBlur = 0;
        });
    }

    drawTooltip() {
        const { ctx, hoveredUnit: unit } = this;

        if (!unit) return;

        const x = unit.renderX + unit.renderWidth / 2;
        const y = unit.renderY - 10;

        const fileName = getUnitLabel(unit.payload, unit.unit_id, this.labelField);
        const duration = unit.execution_time_seconds ?
            `${unit.execution_time_seconds.toFixed(1)}s` : 'In progress';
        const text = `${fileName} (${duration})`;

        ctx.font = '11px Inter, sans-serif';
        const textWidth = ctx.measureText(text).width;
        const padding = 8;
        const tooltipWidth = textWidth + padding * 2;
        const tooltipHeight = 24;

        let tx = x - tooltipWidth / 2;
        tx = Math.max(10, Math.min(tx, this.canvas.width - tooltipWidth - 10));
        const ty = y - tooltipHeight;

        ctx.fillStyle = '#27272a';
        ctx.strokeStyle = '#3f3f46';
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(tx, ty, tooltipWidth, tooltipHeight, 4);
        } else {

            ctx.rect(tx, ty, tooltipWidth, tooltipHeight);
        }
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = '#e4e4e7';
        ctx.textAlign = 'center';
        ctx.fillText(text, tx + tooltipWidth / 2, ty + 16);
    }

    resize() {
        this.canvas.width = this.canvas.offsetWidth;
        this.canvas.height = Math.max(
            this.margin.top + this.margin.bottom + this.data.workers.length * this.rowHeight,
            100
        );
        this.render();
    }
}

export function Timeline({ workers = [], units = [], onUnitClick, labelField = null }) {
    const canvasRef = useRef(null);
    const vizRef = useRef(null);

    useEffect(() => {
        if (canvasRef.current && !vizRef.current) {
            const canvas = canvasRef.current;
            canvas.width = canvas.offsetWidth;
            canvas.height = 200;

            vizRef.current = new TimelineVisualization(canvas);
            vizRef.current.onClick = onUnitClick;
            vizRef.current.labelField = labelField;
        }

        return () => {
            vizRef.current = null;
        };
    }, []);

    useEffect(() => {
        if (vizRef.current) {
            vizRef.current.labelField = labelField;
            vizRef.current.setData(workers, units);
            vizRef.current.resize();
        }
    }, [workers, units, labelField]);

    return html`
        <div class="card" style="margin-bottom: var(--space-6)">
            <h3 class="card-title">Timeline</h3>
            <div style="overflow-x: auto">
                <canvas
                    ref=${canvasRef}
                    style="width: 100%; min-width: 500px; height: 200px; border-radius: var(--radius-md);"
                ></canvas>
            </div>
            <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: var(--space-2); text-align: center">
                Click on a bar to view unit details
            </p>
        </div>
    `;
}

export default Timeline;
