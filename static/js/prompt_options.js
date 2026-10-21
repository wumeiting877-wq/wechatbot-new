(function (global) {
    'use strict';

    var availablePrompts = [];
    var promptLoadState = 'idle';

    function normalizePromptList(data) {
        if (Array.isArray(data)) {
            return data;
        }
        if (data && Array.isArray(data.prompts)) {
            return data.prompts;
        }
        return null;
    }

    async function loadPromptOptions() {
        try {
            const response = await fetch('/api/prompts', {
                headers: { 'Accept': 'application/json' }
            });
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            const data = await response.json();
            const list = normalizePromptList(data);
            if (!list) {
                throw new Error('Prompt API 返回结构异常: ' + JSON.stringify(data));
            }
            availablePrompts = list
                .map(item => {
                    if (typeof item === 'string') return item;
                    if (item && typeof item === 'object') {
                        return item.name || item.id || item.filename || '';
                    }
                    return '';
                })
                .map(name => String(name).trim())
                .filter(Boolean);
            promptLoadState = availablePrompts.length ? 'ok' : 'empty';
            return availablePrompts;
        } catch (error) {
            console.error('Prompt 加载失败:', error);
            promptLoadState = 'error';
            availablePrompts = [];
            return [];
        }
    }

    function bindPromptSelectChange(selectEl) {
        if (!selectEl || selectEl.dataset.promptBound === '1') return;
        selectEl.addEventListener('change', function() {
            this.setAttribute('data-selected', this.value);
            this.classList.remove('listen-field-error');
        });
        selectEl.dataset.promptBound = '1';
    }

    function fillPromptSelect(selectEl, selectedValue, options) {
        if (!selectEl) return;
        const opts = options || {};
        const placeholderText = opts.placeholder || '-- 选择 Prompt --';
        const current = selectedValue !== undefined
            ? selectedValue
            : (selectEl.getAttribute('data-selected') || selectEl.value || '');

        selectEl.innerHTML = '';

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = placeholderText;
        selectEl.appendChild(placeholder);

        if (promptLoadState === 'error') {
            const errorOpt = document.createElement('option');
            errorOpt.value = '';
            errorOpt.disabled = true;
            errorOpt.textContent = 'Prompt 加载失败，请重试';
            selectEl.appendChild(errorOpt);
            if (current) {
                const keepOpt = document.createElement('option');
                keepOpt.value = current;
                keepOpt.textContent = current;
                keepOpt.selected = true;
                selectEl.appendChild(keepOpt);
            }
            bindPromptSelectChange(selectEl);
            return;
        }

        if (promptLoadState === 'empty') {
            const emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.disabled = true;
            emptyOpt.textContent = '暂无可用 Prompt，请先前往 Prompt 管理创建';
            selectEl.appendChild(emptyOpt);
            if (current) {
                const missing = document.createElement('option');
                missing.value = current;
                missing.textContent = '原 Prompt 已不存在';
                missing.selected = true;
                selectEl.appendChild(missing);
            }
            bindPromptSelectChange(selectEl);
            return;
        }

        let found = false;
        availablePrompts.forEach(name => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            if (current && name === current) {
                option.selected = true;
                found = true;
            }
            selectEl.appendChild(option);
        });

        if (current && !found) {
            const missing = document.createElement('option');
            missing.value = current;
            missing.textContent = '原 Prompt 已不存在';
            missing.selected = true;
            selectEl.appendChild(missing);
        } else if (!current) {
            placeholder.selected = true;
        }

        selectEl.setAttribute('data-selected', current);
        bindPromptSelectChange(selectEl);
    }

    function refreshPromptSelects(selector, options) {
        document.querySelectorAll(selector).forEach(selectEl => {
            fillPromptSelect(selectEl, undefined, options);
        });
    }

    function clearListenFieldErrors(container) {
        if (!container) return;
        container.querySelectorAll('.listen-field-error').forEach(el => {
            el.classList.remove('listen-field-error');
        });
    }

    function validateListenRows(containerSelector) {
        const container = document.querySelector(containerSelector || '#listen-list');
        if (!container) {
            return { ok: true, rows: [] };
        }
        clearListenFieldErrors(container);
        const entries = container.querySelectorAll('.entry');
        for (let index = 0; index < entries.length; index += 1) {
            const row = entries[index];
            const nameInput = row.querySelector('input[name="nickname"]');
            const promptSelect = row.querySelector('select[name="prompt_file"]');
            const nickname = nameInput ? nameInput.value.trim() : '';
            const promptFile = promptSelect ? String(promptSelect.value || '').trim() : '';
            const rowNumber = index + 1;
            if (!nickname) {
                if (nameInput) {
                    nameInput.classList.add('listen-field-error');
                    nameInput.focus();
                }
                return {
                    ok: false,
                    row: rowNumber,
                    field: 'nickname',
                    message: '第 ' + rowNumber + ' 个监听对象未填写监听对象名称'
                };
            }
            if (!promptFile) {
                if (promptSelect) {
                    promptSelect.classList.add('listen-field-error');
                    promptSelect.focus();
                }
                return {
                    ok: false,
                    row: rowNumber,
                    field: 'prompt_file',
                    message: '监听对象「' + nickname + '」尚未选择 Prompt'
                };
            }
        }
        const names = [];
        for (let index = 0; index < entries.length; index += 1) {
            const row = entries[index];
            const nameInput = row.querySelector('input[name="nickname"]');
            const nickname = nameInput ? nameInput.value.trim() : '';
            if (names.indexOf(nickname) !== -1) {
                if (nameInput) {
                    nameInput.classList.add('listen-field-error');
                    nameInput.focus();
                }
                return {
                    ok: false,
                    row: index + 1,
                    field: 'nickname',
                    message: '存在重复监听对象名称。'
                };
            }
            names.push(nickname);
        }
        return { ok: true };
    }

    function apiErrorMessage(errorData, fallback) {
        if (!errorData || typeof errorData !== 'object') {
            return fallback || '未知错误';
        }
        const message = errorData.message || '';
        const detail = errorData.detail || '';
        if (message && detail && detail !== message) {
            return message + '：' + detail;
        }
        return message || detail || errorData.error || fallback || '未知错误';
    }

    global.PromptOptions = {
        load: loadPromptOptions,
        fillSelect: fillPromptSelect,
        refreshSelects: refreshPromptSelects,
        validateListenRows: validateListenRows,
        apiErrorMessage: apiErrorMessage,
        getNames: function() { return availablePrompts.slice(); },
        getState: function() { return promptLoadState; }
    };
    global.loadPromptOptions = loadPromptOptions;
    global.fillPromptSelect = fillPromptSelect;
})(window);
