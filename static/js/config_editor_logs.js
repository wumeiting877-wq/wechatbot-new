        let userHoveringLogs = false;
        const logContainer = document.getElementById('log-container');
        const logElement = document.getElementById('logs');
        const maxLogLines = 200;
        let logScrollTimeout;

        if (logContainer) {
            logContainer.addEventListener('mouseenter', () => {
                clearTimeout(logScrollTimeout);
                userHoveringLogs = true;
            });
            logContainer.addEventListener('mouseleave', () => {
                userHoveringLogs = false;
                const currentPanelIsLogs = document.querySelector('.sidebar a.active[data-target="section-logs"]');
                if(currentPanelIsLogs && logContainer.classList.contains('expanded')) {
                    logScrollTimeout = setTimeout(() => {
                        if(!userHoveringLogs) {
                           logContainer.scrollTop = logContainer.scrollHeight;
                        }
                    }, 3000);
                }
            });
        }

        const initEventSource = () => {
            const es = new EventSource('/stream');
            es.addEventListener('message', e => {
                if(e.data.trim()) {
                    const logType = e.data.includes('ERROR') ? 'error' : e.data.includes('WARNING') ? 'warning' : 'info';
                    addLogEntry(e.data, logType);
                }
            });
            es.addEventListener('error', (e) => {
                console.error('SSE Error:', e); es.close();
                addLogEntry('[系统] 日志连接中断，5秒后尝试重连...', 'error');
                setTimeout(initEventSource, 5000);
            });
        };
        initEventSource();

        function addLogEntry(text, type = 'info') {
            if (!logElement || !logContainer) return;
            const categoryFilter = document.getElementById('logCategoryFilter');
            const raw = String(text || '');
            let category = (type || 'info').toUpperCase();
            ['SECURITY', 'MESSAGE', 'SYSTEM', 'BOT', 'AI', 'ERROR', 'WARNING', 'INFO'].forEach(name => {
                if (raw.toUpperCase().includes('[' + name + ']') || raw.toUpperCase().includes(name + ' ')) {
                    category = name;
                }
            });
            if (categoryFilter && categoryFilter.value && category !== categoryFilter.value) {
                return;
            }
            const entry = document.createElement('div');
            entry.innerHTML = ansiToHtml(text);
            entry.className = `log-entry ${type}`;
            entry.dataset.category = category;
            entry.style.whiteSpace = 'pre-wrap';
            logElement.appendChild(entry);

            if(!userHoveringLogs && logContainer.classList.contains('expanded')) {
                 const isNearBottom = logContainer.scrollHeight - logContainer.clientHeight - logContainer.scrollTop < 50;
                 if(isNearBottom) {
                    clearTimeout(logScrollTimeout);
                    logScrollTimeout = setTimeout(() => {
                        if (!userHoveringLogs) {
                           logContainer.scrollTop = logContainer.scrollHeight;
                        }
                    }, 100);
                 }
            }
            while(logElement.children.length > maxLogLines) {
                if (logElement.firstChild) {
                    logElement.removeChild(logElement.firstChild);
                } else {
                    break; 
                }
            }
        }

        if (logContainer) {
            const activeLogTab = document.querySelector('.sidebar a.active[data-target="section-logs"]');
            if (!activeLogTab) {
                logContainer.classList.add('collapsed');
                logContainer.classList.remove('expanded');
            }
        }

        const legalToggle = document.getElementById('toggleLegal');
        if(legalToggle) {
            legalToggle.addEventListener('click', function() {
                var content = document.getElementById('legalContent');
                if (content.style.display === 'none' || content.style.display === '') {
                    content.style.display = 'block'; this.textContent = '隐藏系统声明';
                } else {
                    content.style.display = 'none'; this.textContent = '显示系统声明';
                }
            });
        }

        function updateForumButtons() {
            const select = document.getElementById('forumCharacterSelect');
            const viewBtn = document.querySelector('.forum-view-btn');
            
            if (select && viewBtn) {
                if (select.value) {
                    viewBtn.disabled = false;
                } else {
                    viewBtn.disabled = true;
                }
            }
        }

        function openForum() {
            const select = document.getElementById('forumCharacterSelect');
            if (!select || !select.value) {
                alert('请先选择角色');
                return;
            }
            window.open(`/forum/${select.value}`, '_blank');
        }

        function updateNpcSelection() {
            // 保持容器常显，仅在需要时用于其他联动
            const list = document.getElementById('npc-list');
            if (!list) return;
        }

        function addNpcInput() {}
        function removeNpcInput() {}

        function toggleNpcCard(cardId) {
            const card = document.getElementById(cardId);
            if (!card) return;
            card.classList.toggle('collapsed');
        }

        // 生成单个 NPC 行（名称 + 操作区）
        function createNpcRow(initialName = '', initialSettings = null) {
            const row = document.createElement('div');
            row.className = 'entry npc-entry';

            const nameInput = document.createElement('input');
            nameInput.type = 'text';
            nameInput.placeholder = 'NPC名字';
            nameInput.value = initialName || '';
            nameInput.required = true;

            const actions = document.createElement('div');
            actions.className = 'npc-actions';

            const toggleBtn = document.createElement('button');
            toggleBtn.type = 'button';
            toggleBtn.className = 'toggle-btn';
            toggleBtn.textContent = '展开/收起设定';

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.textContent = '删除';

            actions.appendChild(toggleBtn);
            actions.appendChild(removeBtn);

            // 占位容器：详细设置
            const detail = document.createElement('div');
            detail.className = 'npc-detail';
            detail.style.display = 'none';
            const detailId = `npc_detail_${Date.now()}_${Math.random().toString(36).slice(2,7)}`;
            detail.id = detailId;

            // 详细设置表单
            detail.innerHTML = `
                <div class="npc-setting-group">
                    <label>语言风格:</label>
                    <select class="npc_languageStyle">
                        <option value="formal">正式</option>
                        <option value="casual">随意</option>
                        <option value="friendly">友好</option>
                        <option value="professional">专业</option>
                        <option value="humorous">幽默</option>
                        <option value="serious">严肃</option>
                    </select>
                </div>
                <div class="npc-setting-group">
                    <label>关系:</label>
                    <select class="npc_relationship">
                        <option value="friend">朋友</option>
                        <option value="colleague">同事</option>
                        <option value="family">家人</option>
                        <option value="stranger">陌生人</option>
                        <option value="mentor">导师</option>
                        <option value="student">学生</option>
                    </select>
                </div>
                <div class="npc-setting-group">
                    <label>示例输出:</label>
                    <textarea class="npc_exampleOutput" placeholder="输入NPC的示例回复风格..."></textarea>
                </div>
                <div class="npc-setting-group">
                    <label>其他设置:</label>
                    <textarea class="npc_otherSettings" placeholder="其他特殊要求或设定..."></textarea>
                </div>
            `;

            // 初始化设置
            if (initialSettings) {
                detail.querySelector('.npc_languageStyle').value = initialSettings.language_style || 'casual';
                detail.querySelector('.npc_relationship').value = initialSettings.relationship || 'friend';
                detail.querySelector('.npc_exampleOutput').value = initialSettings.example_output || '';
                detail.querySelector('.npc_otherSettings').value = initialSettings.other_settings || '';
            }

            // 交互
            toggleBtn.onclick = () => {
                detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
            };
            removeBtn.onclick = () => {
                row.remove();
                updateNpcSelection();
            };

            row.appendChild(nameInput);
            row.appendChild(actions);
            row.appendChild(detail);

            return row;
        }

        function addNpcRow() {
            const list = document.getElementById('npc-list');
            const row = createNpcRow();
            // 收起其它已展开的NPC设定
            const allDetails = list.querySelectorAll('.npc-detail');
            allDetails.forEach(function(detail) {
                detail.style.display = 'none';
            });
            // 添加并默认展开新建NPC的设定
            list.appendChild(row);
            const newDetail = row.querySelector('.npc-detail');
            if (newDetail) {
                newDetail.style.display = 'block';
            }
            updateNpcSelection();
        }

        function clearAllNpcs() {
            const list = document.getElementById('npc-list');
            list.innerHTML = '';
            updateNpcSelection();
        }

        async function saveNpcSettings() {
            const list = document.getElementById('npc-list');
            const rows = Array.from(list.querySelectorAll('.entry.npc-entry'));
            const names = [];
            const npcSettings = {};

            for (const row of rows) {
                const name = row.querySelector('input[type="text"]').value.trim();
                if (!name) continue;
                if (names.includes(name)) {
                    alert(`存在重复的NPC名字：${name}`);
                    return;
                }
                names.push(name);
                const detail = row.querySelector('.npc-detail');
                npcSettings[name] = {
                    language_style: detail.querySelector('.npc_languageStyle').value,
                    relationship: detail.querySelector('.npc_relationship').value,
                    example_output: detail.querySelector('.npc_exampleOutput').value,
                    other_settings: detail.querySelector('.npc_otherSettings').value
                };
            }

            if (names.length === 0) {
                alert('请至少添加一个NPC');
                return;
            }

            const configData = {
                selected_npcs: names,
                npc_settings: npcSettings
            };

            try {
                // 保存到localStorage（兼容旧逻辑）
                const localStorageData = { npcs: names };
                localStorage.setItem('npcSettings', JSON.stringify(localStorageData));

                const response = await fetch('/api/npc/save_settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(configData)
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                const result = await response.json();
                console.log('NPC设置已保存到后端:', result);
                alert('NPC设置已保存！论坛NPC将按配置生成回复。');
            } catch (error) {
                console.error('保存NPC设置失败:', error);
                alert(`保存NPC设置失败: ${error.message}`);
            }
        }

