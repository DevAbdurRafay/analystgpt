/**
 * Custom dropdown — replaces native <select> with styled div/li UI.
 * Syncs selected value back to the hidden native select for existing JS compatibility.
 */
(function () {
    const OPEN_DROPDOWNS = new Set();

    class CustomDropdown {
        constructor(selectEl) {
            this.select = selectEl;
            this.options = Array.from(selectEl.options);
            this.isOpen = false;
            this.highlightIndex = this.getSelectedIndex();
            this.build();
            this.bindEvents();
            this.select._customDropdown = this;
        }

        getSelectedIndex() {
            return Math.max(0, this.select.selectedIndex);
        }

        build() {
            this.select.classList.add('custom-dropdown-native');
            this.select.setAttribute('tabindex', '-1');
            this.select.setAttribute('aria-hidden', 'true');

            this.wrapper = document.createElement('div');
            this.wrapper.className = 'custom-dropdown relative inline-block min-w-[7rem]';

            this.trigger = document.createElement('button');
            this.trigger.type = 'button';
            this.trigger.className =
                'custom-dropdown-trigger w-full flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 border border-white/[0.15] bg-[#0f172a] text-[#e2e8f0] text-sm focus:outline-none focus:border-cyberCyan focus:ring-1 focus:ring-cyberCyan transition-all';
            this.trigger.setAttribute('aria-haspopup', 'listbox');
            this.trigger.setAttribute('aria-expanded', 'false');

            this.labelSpan = document.createElement('span');
            this.labelSpan.className = 'custom-dropdown-label truncate';

            this.chevron = document.createElement('i');
            this.chevron.className = 'fa-solid fa-chevron-down text-[10px] text-slate-400 transition-transform';

            this.trigger.appendChild(this.labelSpan);
            this.trigger.appendChild(this.chevron);

            this.list = document.createElement('ul');
            this.list.className =
                'custom-dropdown-list hidden absolute z-50 mt-1 w-full min-w-[8rem] max-h-56 overflow-y-auto rounded-lg border border-white/[0.12] bg-[#0f172a] shadow-xl shadow-black/40 py-1';
            this.list.setAttribute('role', 'listbox');

            this.optionEls = this.options.map((opt, index) => {
                const li = document.createElement('li');
                li.className =
                    'custom-dropdown-option flex items-center justify-between gap-2 px-2.5 py-1.5 text-sm text-[#e2e8f0] cursor-pointer transition-colors';
                li.setAttribute('role', 'option');
                li.dataset.value = opt.value;
                li.dataset.index = String(index);

                const textSpan = document.createElement('span');
                textSpan.textContent = opt.textContent.trim();

                const check = document.createElement('i');
                check.className = 'fa-solid fa-check text-cyberCyan text-[10px] opacity-0';

                li.appendChild(textSpan);
                li.appendChild(check);
                this.list.appendChild(li);
                return li;
            });

            this.wrapper.appendChild(this.trigger);
            this.wrapper.appendChild(this.list);
            this.select.parentNode.insertBefore(this.wrapper, this.select.nextSibling);

            this.syncDisplay();
        }

        bindEvents() {
            this.trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggle();
            });

            this.optionEls.forEach((li) => {
                li.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.selectOption(parseInt(li.dataset.index, 10));
                });
                li.addEventListener('mouseenter', () => {
                    this.highlightIndex = parseInt(li.dataset.index, 10);
                    this.updateHighlight();
                });
            });

            this.trigger.addEventListener('keydown', (e) => this.onKeyDown(e));
            this.list.addEventListener('keydown', (e) => this.onKeyDown(e));

            document.addEventListener('click', () => {
                if (this.isOpen) this.close();
            });
        }

        onKeyDown(e) {
            if (!this.isOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault();
                this.open();
                return;
            }
            if (!this.isOpen) return;

            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    this.highlightIndex = Math.min(this.highlightIndex + 1, this.options.length - 1);
                    this.updateHighlight();
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    this.highlightIndex = Math.max(this.highlightIndex - 1, 0);
                    this.updateHighlight();
                    break;
                case 'Enter':
                case ' ':
                    e.preventDefault();
                    this.selectOption(this.highlightIndex);
                    break;
                case 'Escape':
                    e.preventDefault();
                    this.close();
                    this.trigger.focus();
                    break;
                case 'Tab':
                    this.close();
                    break;
                default:
                    break;
            }
        }

        toggle() {
            if (this.isOpen) this.close();
            else this.open();
        }

        open() {
            OPEN_DROPDOWNS.forEach((dd) => {
                if (dd !== this) dd.close();
            });
            this.isOpen = true;
            OPEN_DROPDOWNS.add(this);
            this.list.classList.remove('hidden');
            this.trigger.setAttribute('aria-expanded', 'true');
            this.chevron.classList.add('rotate-180');
            this.highlightIndex = this.getSelectedIndex();
            this.updateHighlight();
        }

        close() {
            this.isOpen = false;
            OPEN_DROPDOWNS.delete(this);
            this.list.classList.add('hidden');
            this.trigger.setAttribute('aria-expanded', 'false');
            this.chevron.classList.remove('rotate-180');
        }

        updateHighlight() {
            this.optionEls.forEach((li, i) => {
                const selected = li.dataset.value === this.select.value;
                li.classList.toggle('bg-[#164e63]', i === this.highlightIndex);
                li.classList.toggle('text-white', i === this.highlightIndex);
                li.querySelector('.fa-check').classList.toggle('opacity-100', selected);
                li.querySelector('.fa-check').classList.toggle('opacity-0', !selected);
                li.setAttribute('aria-selected', selected ? 'true' : 'false');
            });
        }

        syncDisplay() {
            const selected = this.options[this.getSelectedIndex()];
            this.labelSpan.textContent = selected ? selected.textContent.trim() : '';
            this.updateHighlight();
        }

        selectOption(index) {
            if (index < 0 || index >= this.options.length) return;
            const opt = this.options[index];
            this.select.value = opt.value;
            this.select.selectedIndex = index;
            this.syncDisplay();
            this.close();
            this.select.dispatchEvent(new Event('change', { bubbles: true }));
        }

        setValue(value) {
            const index = this.options.findIndex((o) => o.value === value);
            if (index >= 0) {
                this.select.value = value;
                this.select.selectedIndex = index;
                this.syncDisplay();
            }
        }
    }

    function initCustomDropdowns(root) {
        const scope = root || document;
        scope.querySelectorAll('select:not([data-custom-dropdown-init])').forEach((sel) => {
            if (sel.options.length === 0) return;
            sel.dataset.customDropdownInit = 'true';
            new CustomDropdown(sel);
        });
    }

    window.initCustomDropdowns = initCustomDropdowns;
    window.setCustomDropdownValue = function (selectEl, value) {
        if (selectEl && selectEl._customDropdown) {
            selectEl._customDropdown.setValue(value);
        } else if (selectEl) {
            selectEl.value = value;
        }
    };

    document.addEventListener('DOMContentLoaded', () => initCustomDropdowns());
})();
