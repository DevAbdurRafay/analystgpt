(function () {
    const STORAGE_KEY = 'analystgpt-theme';
    const THEMES = ['dark', 'light'];
    let cursorRafId = null;
    let pendingCursor = null;

    function getTheme() {
        const current = document.documentElement.getAttribute('data-theme');
        return THEMES.includes(current) ? current : 'dark';
    }

    function getPlotlyTheme() {
        const isLight = getTheme() === 'light';
        return {
            isLight,
            fontColor: isLight ? '#0f172a' : '#E2E8F0',
            mutedColor: isLight ? '#475569' : '#94A3B8',
            titleColor: isLight ? 'rgba(15,23,42,0.85)' : 'rgba(226,232,240,0.7)',
            gridColor: isLight ? 'rgba(15,23,42,0.08)' : 'rgba(255,255,255,0.05)',
            tickColor: isLight ? 'rgba(15,23,42,0.15)' : 'rgba(255,255,255,0.1)',
        };
    }

    function updateToggleIcon(theme) {
        const icon = document.getElementById('theme-icon');
        if (!icon) return;
        icon.className = theme === 'light'
            ? 'fa-solid fa-moon text-sm'
            : 'fa-solid fa-sun text-sm';
    }

    function updateCursorAura(theme, x, y) {
        const aura = document.getElementById('cursor-aura');
        if (!aura) return;

        const px = x ?? aura.dataset.x;
        const py = y ?? aura.dataset.y;
        if (px === undefined || py === undefined) return;

        if (theme === 'light') {
            aura.style.background = `radial-gradient(700px circle at ${px}px ${py}px, rgba(6, 182, 212, 0.12), rgba(16, 185, 129, 0.08), transparent 70%)`;
        } else {
            aura.style.background = `radial-gradient(700px circle at ${px}px ${py}px, rgba(6, 182, 212, 0.14), rgba(16, 185, 129, 0.08), transparent 70%)`;
        }
    }

    function applyTheme(theme, persist) {
        const next = THEMES.includes(theme) ? theme : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        if (persist) {
            localStorage.setItem(STORAGE_KEY, next);
        }
        updateToggleIcon(next);
        updateCursorAura(next);
        window.dispatchEvent(new CustomEvent('analystgpt-theme-change', { detail: { theme: next } }));
    }

    function toggleTheme() {
        applyTheme(getTheme() === 'dark' ? 'light' : 'dark', true);
    }

    function scheduleCursorUpdate(clientX, clientY) {
        pendingCursor = { clientX, clientY };
        if (cursorRafId) return;
        cursorRafId = requestAnimationFrame(function () {
            cursorRafId = null;
            if (!pendingCursor) return;
            const { clientX, clientY } = pendingCursor;
            pendingCursor = null;
            const aura = document.getElementById('cursor-aura');
            if (!aura) return;
            aura.dataset.x = String(clientX);
            aura.dataset.y = String(clientY);
            updateCursorAura(getTheme(), clientX, clientY);
        });
    }

    window.getAppTheme = getTheme;
    window.getPlotlyTheme = getPlotlyTheme;

    document.addEventListener('DOMContentLoaded', () => {
        const saved = localStorage.getItem(STORAGE_KEY) || 'dark';
        applyTheme(saved, false);

        const btn = document.getElementById('theme-toggle');
        if (btn) {
            btn.addEventListener('click', toggleTheme);
        }

        document.addEventListener('mousemove', (e) => {
            scheduleCursorUpdate(e.clientX, e.clientY);
        });
    });
})();
