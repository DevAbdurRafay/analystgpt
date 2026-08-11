(function () {
    const NAME_FILTER = /[^A-Za-z\s]/g;

    const STRENGTH_LEVELS = [
        { label: "", className: "" },
        { label: "Weak", className: "level-weak" },
        { label: "Fair", className: "level-fair" },
        { label: "Fair", className: "level-fair" },
        { label: "Strong", className: "level-strong" },
    ];

    function passwordStrengthScore(password) {
        if (!password) return 0;
        let score = 0;
        if (/[A-Z]/.test(password)) score += 1;
        if (/[a-z]/.test(password)) score += 1;
        if (/[0-9]/.test(password)) score += 1;
        if (/[^A-Za-z0-9]/.test(password)) score += 1;
        return score;
    }

    function isValidFullName(name) {
        const cleaned = (name || "").trim().replace(/\s+/g, " ");
        if (cleaned.length < 2) return false;
        return /^[A-Za-z]+(?: [A-Za-z]+)*$/.test(cleaned);
    }

    function isValidPassword(password) {
        return passwordStrengthScore(password) === 4;
    }

    function filterNameInput(input) {
        if (!input) return;
        const start = input.selectionStart;
        const end = input.selectionEnd;
        const filtered = input.value.replace(NAME_FILTER, "");
        if (filtered !== input.value) {
            input.value = filtered;
            if (start !== null && end !== null) {
                input.setSelectionRange(start - 1, end - 1);
            }
        }
    }

    function isRegisterMode() {
        const nameGroup = document.getElementById("full-name-group");
        return Boolean(nameGroup && !nameGroup.classList.contains("hidden"));
    }

    function getStrengthElements(wrapId, labelId) {
        const wrap = document.getElementById(wrapId || "password-strength-wrap");
        if (!wrap) return null;
        return {
            wrap,
            steps: wrap.querySelectorAll(".password-strength-step"),
            meter: wrap.querySelector(".password-strength-steps"),
            label: document.getElementById(labelId || "password-strength-label"),
        };
    }

    function resetPasswordStrengthUI(elements) {
        if (!elements) return;
        elements.wrap.classList.add("hidden");
        elements.wrap.setAttribute("aria-hidden", "true");
        elements.wrap.classList.remove("level-weak", "level-fair", "level-strong");
        elements.steps.forEach((step) => {
            step.classList.remove("active", "step-weak", "step-fair", "step-strong");
        });
        if (elements.label) {
            elements.label.textContent = "";
            elements.label.className = "password-strength-label";
        }
        if (elements.meter) {
            elements.meter.setAttribute("aria-valuenow", "0");
        }
    }

    function updatePasswordStrengthBar(passwordInput, options = {}) {
        const elements = getStrengthElements(options.wrapId, options.labelId);
        if (!passwordInput || !elements || !elements.steps.length) return;

        if (document.getElementById("full-name-group") && !isRegisterMode()) {
            resetPasswordStrengthUI(elements);
            return;
        }

        const score = passwordStrengthScore(passwordInput.value);
        elements.wrap.classList.remove("level-weak", "level-fair", "level-strong");
        elements.steps.forEach((step) => {
            step.classList.remove("active", "step-weak", "step-fair", "step-strong");
        });

        if (!passwordInput.value) {
            resetPasswordStrengthUI(elements);
            return;
        }

        elements.wrap.classList.remove("hidden");
        elements.wrap.setAttribute("aria-hidden", "false");

        const level = STRENGTH_LEVELS[score] || STRENGTH_LEVELS[0];
        if (level.className) {
            elements.wrap.classList.add(level.className);
        }

        elements.steps.forEach((step, index) => {
            if (index >= score) return;
            step.classList.add("active");
            if (score <= 1) step.classList.add("step-weak");
            else if (score <= 3) step.classList.add("step-fair");
            else step.classList.add("step-strong");
        });

        if (elements.label && level.label) {
            elements.label.textContent = level.label;
            elements.label.className = `password-strength-label ${level.className}`;
        }

        if (elements.meter) {
            elements.meter.setAttribute("aria-valuenow", String(score));
        }
    }

    function bindNameField(input) {
        if (!input) return;
        input.addEventListener("input", () => filterNameInput(input));
        input.addEventListener("paste", (e) => {
            e.preventDefault();
            const text = (e.clipboardData || window.clipboardData).getData("text");
            input.value = (input.value + text).replace(NAME_FILTER, "");
        });
    }

    function bindPasswordStrength(passwordInput, options = {}) {
        if (!passwordInput) return;
        const refresh = () => updatePasswordStrengthBar(passwordInput, options);
        passwordInput.addEventListener("input", refresh);
        refresh();
    }

    function setPasswordStrengthVisible(visible) {
        const elements = getStrengthElements();
        if (!elements) return;
        if (!visible) {
            resetPasswordStrengthUI(elements);
        }
    }

    window.AuthValidation = {
        passwordStrengthScore,
        isValidFullName,
        isValidPassword,
        bindNameField,
        bindPasswordStrength,
        setPasswordStrengthVisible,
        filterNameInput,
    };
})();
