// Despesas: a lista de notas, o envio das fotos, a conferência do Controle, a
// validação do Financeiro e o histórico. As telas trocam pelo endereço
// (#enviar, #nota-12): o voltar do celular volta para a tela anterior.

(() => {
    const content = document.getElementById('content');
    const csrfToken = content.dataset.csrfToken;
    const readJson = (id) => JSON.parse(document.getElementById(id).textContent);

    const access = readJson('expenses-access');
    const types = readJson('expenses-types');
    const limits = readJson('expenses-limits');
    const statuses = readJson('expenses-statuses');
    const openExpense = readJson('expenses-open');
    const reviewer = access.control || access.finance;
    const accepted = limits.accepted.split(',');

    const urlFor = (name, id) => content.dataset[name].replace('/0/', `/${id}/`);

    const state = {
        scope: reviewer ? 'queue' : 'mine',
        page: 1,
        expense: null,
        items: [],
        history: null,
        // A mensagem que aparece depois da troca de tela (a troca limpa as mensagens)
        flash: null,
    };

    // ---------- Utilitários ----------

    const moneyFormat = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

    function toCents(text) {
        let value = String(text ?? '').trim().replace(/\s|R\$/g, '');
        if (!value) return null;
        // 1.234,56 e 1234,56 viram 1234.56; 1234.56 fica como está
        if (value.includes(',')) value = value.replace(/\./g, '').replace(',', '.');
        const number = Number(value);
        return Number.isFinite(number) ? Math.round(number * 100) : NaN;
    }

    function toApiDecimal(text) {
        let value = String(text ?? '').trim().replace(/\s|R\$/g, '');
        if (value.includes(',')) value = value.replace(/\./g, '').replace(',', '.');
        return value;
    }

    const formatMoney = (cents) => moneyFormat.format((cents || 0) / 100);
    const toInputDecimal = (value) => (value === '' || value === null || value === undefined) ? '' : String(value).replace('.', ',');

    function formatQuantity(value) {
        const number = Number(value);
        return Number.isFinite(number) ? String(Number(number.toFixed(3))).replace('.', ',') : String(value);
    }

    function element(tag, attributes = {}, children = []) {
        const node = document.createElement(tag);
        for (const [name, value] of Object.entries(attributes)) {
            if (value === null || value === undefined || value === false) continue;
            if (name === 'text') node.textContent = value;
            else if (name === 'className') node.className = value;
            else if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
            else node.setAttribute(name, value === true ? '' : value);
        }
        for (const child of [].concat(children)) {
            if (child === null || child === undefined || child === false) continue;
            node.append(child instanceof Node ? child : document.createTextNode(String(child)));
        }
        return node;
    }

    const icon = (name) => element('i', { className: `fas ${name}`, 'aria-hidden': 'true' });

    async function api(url, options = {}) {
        let response;
        try {
            response = await fetch(url, {
                credentials: 'same-origin',
                ...options,
                headers: { 'X-CSRFToken': csrfToken, ...(options.headers || {}) },
            });
        } catch {
            throw Object.assign(new Error('Sem conexão com o portal. Confira a internet e tente de novo.'), { status: 0 });
        }
        let data = {};
        try {
            data = await response.json();
        } catch {
            data = {};
        }
        if (!response.ok) {
            const message = data.detail || (response.status === 413
                ? 'As fotos passam do tamanho aceito. Envie fotos menores.'
                : 'Não foi possível concluir. Tente de novo.');
            throw Object.assign(new Error(message), { status: response.status, data });
        }
        return data;
    }

    const postJson = (url, payload) => api(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    const alertBox = document.getElementById('alert-error');
    const successBox = document.getElementById('success-message');

    function showError(message) {
        document.getElementById('alert-error-text').textContent = message;
        alertBox.hidden = false;
        successBox.hidden = true;
        alertBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function showSuccess(message) {
        successBox.textContent = message;
        successBox.hidden = false;
        alertBox.hidden = true;
    }

    function clearMessages() {
        alertBox.hidden = true;
        successBox.hidden = true;
    }

    function statusBadge(status, label) {
        return element('span', { className: `status-badge status-${status}`, text: label });
    }

    // ---------- Telas ----------

    const views = ['list-view', 'submit-view', 'detail-view'];

    function showView(id) {
        for (const view of views) {
            const node = document.getElementById(view);
            if (node) node.hidden = view !== id;
        }
        window.scrollTo(0, 0);
    }

    function route() {
        const hash = window.location.hash;
        const match = hash.match(/^#nota-(\d+)$/);
        if (match) {
            loadDetail(Number(match[1]));
        } else if (hash === '#enviar' && access.employee) {
            showView('submit-view');
        } else {
            showView('list-view');
            loadList();
        }
    }

    window.addEventListener('hashchange', () => {
        clearMessages();
        route();
    });

    // ---------- Lista ----------

    const statusFilter = document.getElementById('status-filter');
    for (const status of statuses) {
        statusFilter.append(element('option', { value: status.value, text: status.label }));
    }

    const searchInput = document.getElementById('search-input');
    let searchTimer;

    function listUrl(page) {
        const params = new URLSearchParams({ scope: state.scope, page });
        if (statusFilter.value) params.set('status', statusFilter.value);
        if (searchInput && searchInput.value.trim()) params.set('q', searchInput.value.trim());
        return `${content.dataset.listUrl}?${params}`;
    }

    function expenseRow(expense) {
        const meta = [
            expense.employee,
            expense.expense_type,
            expense.number ? `Nº ${expense.number}` : '',
            `Enviada em ${expense.created_at}`,
        ].filter(Boolean).join(' · ');
        return element('a', { className: 'expense-row', href: `#nota-${expense.id}` }, [
            element('span', { className: 'row-title' }, [
                `Nota #${expense.id}`,
                statusBadge(expense.status, expense.status_display),
                expense.alerts_count ? element('span', { className: 'alert-count' }, [
                    icon('fa-triangle-exclamation'), ` ${expense.alerts_count} alerta${expense.alerts_count > 1 ? 's' : ''}`,
                ]) : null,
            ]),
            element('span', { className: 'row-meta', text: meta }),
            element('span', { className: 'row-values' }, [
                element('strong', { text: expense.reimbursed_total }),
                expense.total ? `de ${expense.total}` : 'reembolsado',
            ]),
        ]);
    }

    async function loadList(page = 1) {
        state.page = page;
        const list = document.getElementById('expense-list');
        try {
            const data = await api(listUrl(page));
            if (page === 1) list.replaceChildren();
            list.append(...data.expenses.map(expenseRow));
            document.getElementById('list-empty').hidden = list.children.length > 0;
            document.getElementById('list-more').hidden = !data.has_next;
            const counter = document.getElementById('queue-count');
            if (counter) counter.textContent = data.queue_count ? String(data.queue_count) : '';
        } catch (error) {
            showError(error.message);
        }
    }

    document.getElementById('list-more').addEventListener('click', () => loadList(state.page + 1));
    statusFilter.addEventListener('change', () => loadList());
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => loadList(), 300);
        });
    }

    const tabs = document.querySelectorAll('.tab[data-scope]');
    function selectTab(scope) {
        state.scope = scope;
        tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.scope === scope));
    }
    tabs.forEach((tab) => tab.addEventListener('click', () => {
        selectTab(tab.dataset.scope);
        loadList();
    }));
    if (reviewer) selectTab('queue');

    // ---------- Fotos ----------

    function photoPicker(prefix, onChange) {
        const files = [];
        const urls = [];
        const previews = document.getElementById(`${prefix}-previews`);
        const megabytes = Math.round(limits.max_size / (1024 * 1024));

        function render() {
            previews.replaceChildren(...files.map((file, index) => element('figure', {}, [
                element('img', { src: urls[index], alt: `Foto ${index + 1}` }),
                element('button', {
                    type: 'button',
                    className: 'photo-remove',
                    title: 'Remover a foto',
                    'aria-label': `Remover a foto ${index + 1}`,
                    onclick: () => {
                        URL.revokeObjectURL(urls[index]);
                        files.splice(index, 1);
                        urls.splice(index, 1);
                        render();
                    },
                }, [icon('fa-xmark')]),
            ])));
            onChange(files.length);
        }

        function add(list) {
            clearMessages();
            for (const file of list) {
                if (files.length >= limits.max_photos) {
                    showError(`Envie no máximo ${limits.max_photos} fotos por nota.`);
                    break;
                }
                // Alguns celulares não dizem o tipo: aí o servidor confere
                if (file.type && !accepted.includes(file.type)) {
                    showError('Envie apenas fotos nos formatos JPEG, PNG ou WEBP.');
                    continue;
                }
                if (file.size > limits.max_size) {
                    showError(`Cada foto pode ter até ${megabytes} MB.`);
                    continue;
                }
                files.push(file);
                urls.push(URL.createObjectURL(file));
            }
            render();
        }

        for (const source of ['camera', 'gallery']) {
            const input = document.getElementById(`${prefix}-${source}`);
            input.addEventListener('change', () => {
                add(input.files);
                input.value = '';
            });
        }

        return {
            files: () => files.slice(),
            clear() {
                urls.forEach((url) => URL.revokeObjectURL(url));
                files.length = 0;
                urls.length = 0;
                render();
            },
        };
    }

    function photosForm(files, note) {
        const form = new FormData();
        files.forEach((file, index) => form.append('photos', file, file.name || `foto-${index + 1}.jpg`));
        form.append('note', note);
        return form;
    }

    // ---------- Envio ----------

    if (access.employee) {
        const sendButton = document.getElementById('submit-send');
        const submitNote = document.getElementById('submit-note');
        const submitState = document.getElementById('submit-state');
        const picker = photoPicker('submit', (count) => { sendButton.disabled = count === 0; });

        sendButton.addEventListener('click', async () => {
            clearMessages();
            sendButton.disabled = true;
            submitState.hidden = false;
            try {
                const data = await api(content.dataset.listUrl, {
                    method: 'POST',
                    body: photosForm(picker.files(), submitNote.value),
                });
                picker.clear();
                submitNote.value = '';
                state.flash = 'Nota enviada. Ela agora aguarda a conferência do Controle.';
                window.location.hash = `#nota-${data.expense.id}`;
            } catch (error) {
                showError(error.message);
                sendButton.disabled = picker.files().length === 0;
            } finally {
                submitState.hidden = true;
            }
        });
    }

    // ---------- A nota ----------

    const form = document.getElementById('expense-form');
    const fieldInputs = {
        number: document.getElementById('field-number'),
        issue_date: document.getElementById('field-issue-date'),
        cnpj: document.getElementById('field-cnpj'),
        total: document.getElementById('field-total'),
        expense_type: document.getElementById('field-type'),
        access_key: document.getElementById('field-access-key'),
    };
    const typeSelect = fieldInputs.expense_type;
    for (const type of types) typeSelect.append(element('option', { value: type.id, text: type.name }));

    const requiredToApprove = [
        ['number', 'número da nota'],
        ['issue_date', 'data'],
        ['total', 'valor total'],
        ['cnpj', 'CNPJ do emitente'],
        ['expense_type', 'tipo'],
    ];

    function canEdit() {
        return Boolean(state.expense && state.expense.can.edit);
    }

    function itemRow(item, index) {
        const editable = canEdit();
        const update = (name) => (event) => {
            item[name] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
            if (name === 'non_reimbursable') row.classList.toggle('non-reimbursable', item.non_reimbursable);
            refreshTotals();
        };
        const row = element('tr', { className: item.non_reimbursable ? 'non-reimbursable' : '' }, [
            element('td', {}, [
                element('input', {
                    type: 'text', value: item.description, maxlength: 200, disabled: !editable,
                    'aria-label': `Descrição do item ${index + 1}`, oninput: update('description'),
                }),
                item.ai_group ? element('span', { className: 'ai-group', text: `IA: ${item.ai_group}` }) : null,
            ]),
            element('td', {}, [element('input', {
                type: 'text', className: 'item-quantity', inputmode: 'decimal', value: item.quantity,
                disabled: !editable, 'aria-label': `Quantidade do item ${index + 1}`, oninput: update('quantity'),
            })]),
            element('td', {}, [element('input', {
                type: 'text', className: 'item-amount', inputmode: 'decimal', value: item.amount,
                disabled: !editable, 'aria-label': `Valor do item ${index + 1}`, oninput: update('amount'),
            })]),
            element('td', { className: 'item-check' }, [element('input', {
                type: 'checkbox', checked: item.non_reimbursable, disabled: !editable,
                'aria-label': `Item ${index + 1} não reembolsável`, onchange: update('non_reimbursable'),
            })]),
            element('td', {}, editable ? [element('button', {
                type: 'button', className: 'button small danger', title: 'Remover o item',
                'aria-label': `Remover o item ${index + 1}`,
                onclick: () => {
                    state.items.splice(index, 1);
                    renderItems();
                },
            }, [icon('fa-trash')])] : []),
        ]);
        return row;
    }

    function renderItems() {
        document.getElementById('items-body').replaceChildren(...state.items.map(itemRow));
        document.getElementById('items-empty').hidden = state.items.length > 0;
        refreshTotals();
    }

    function totals() {
        let all = 0;
        let reimbursed = 0;
        for (const item of state.items) {
            const cents = toCents(item.amount);
            if (!Number.isFinite(cents)) continue;
            all += cents;
            if (!item.non_reimbursable) reimbursed += cents;
        }
        return { all, reimbursed };
    }

    function missingToApprove() {
        const missing = requiredToApprove
            .filter(([name]) => !fieldInputs[name].value.trim())
            .map(([, label]) => label);
        return missing;
    }

    function refreshTotals() {
        const { all, reimbursed } = totals();
        document.getElementById('items-total').textContent = formatMoney(all);
        document.getElementById('reimbursed-total').textContent = formatMoney(reimbursed);
        refreshApproveHint();
    }

    function refreshApproveHint() {
        const hint = document.getElementById('approve-hint');
        const approve = document.getElementById('approve-button');
        if (!state.expense || !state.expense.can.act) return;
        const problems = [];
        if (canEdit()) {
            const missing = missingToApprove();
            if (missing.length) problems.push(`preencha: ${missing.join(', ')}`);
            if (totals().reimbursed <= 0) problems.push('o valor reembolsado precisa ser maior que zero');
        }
        approve.disabled = problems.length > 0;
        hint.hidden = problems.length === 0;
        hint.textContent = problems.length ? `Para aprovar, ${problems.join('; ')}.` : '';
    }

    Object.values(fieldInputs).forEach((input) => input.addEventListener('input', () => {
        input.classList.remove('invalid');
        refreshApproveHint();
    }));

    document.getElementById('add-item').addEventListener('click', () => {
        state.items.push({ id: null, description: '', quantity: '1', amount: '', non_reimbursable: false, ai_group: '' });
        renderItems();
        const inputs = document.querySelectorAll('#items-body tr:last-child input[type="text"]');
        if (inputs.length) inputs[0].focus();
    });

    function formData() {
        return {
            number: fieldInputs.number.value.trim(),
            issue_date: fieldInputs.issue_date.value,
            cnpj: fieldInputs.cnpj.value.trim(),
            total: toApiDecimal(fieldInputs.total.value),
            expense_type: fieldInputs.expense_type.value,
            access_key: fieldInputs.access_key.value.trim(),
            items: state.items.map((item) => ({
                id: item.id,
                description: item.description.trim(),
                quantity: toApiDecimal(item.quantity),
                amount: toApiDecimal(item.amount),
                non_reimbursable: item.non_reimbursable,
            })),
        };
    }

    function renderNotice(expense) {
        const notice = document.getElementById('detail-notice');
        notice.classList.toggle('danger', expense.status === 'R');
        let text = '';
        if (!reviewer) {
            if (expense.last_note && expense.status === 'S') text = `Correção pedida:\n${expense.last_note}`;
            if (expense.last_note && expense.status === 'R') text = `Motivo da rejeição:\n${expense.last_note}`;
            if (expense.status === 'S' && !text) text = 'O Controle pediu uma correção: envie novas fotos da nota.';
        } else {
            const last = expense.timeline[expense.timeline.length - 1];
            if (last && last.note && expense.status !== 'A') {
                text = `${last.action_display} (${last.role_display}, ${last.author_name}, ${last.created_at}):\n${last.note}`;
            }
        }
        notice.textContent = text;
        notice.hidden = !text;
    }

    function renderPhotos(expense) {
        document.getElementById('detail-photos').replaceChildren(...expense.photos.map((photo, index) => element('a', {
            href: photo.url, target: '_blank', rel: 'noopener', title: 'Abrir a foto em tamanho real',
        }, [
            element('img', { src: photo.url, alt: `Foto ${index + 1} da nota`, loading: 'lazy' }),
            element('span', { className: 'photo-caption', text: `Foto ${index + 1} · toque para ampliar` }),
        ])));
    }

    function renderMeta(expense) {
        const rows = [['Enviada em', expense.created_at]];
        if (reviewer) {
            rows.unshift(['Funcionário', `${expense.employee} (${expense.employee_username})`]);
            rows.push(['Setor', expense.sector || '-'], ['Centro de custo', expense.cost_center || '-']);
        }
        rows.push(['Valor reembolsado', expense.reimbursed_total]);
        document.getElementById('detail-meta').replaceChildren(...rows.flatMap(([label, value]) => [
            element('dt', { text: label }), element('dd', { text: value }),
        ]));
        document.getElementById('detail-employee-note').textContent = expense.employee_note || 'Sem observação.';
    }

    function renderAlerts(expense) {
        const box = document.getElementById('detail-alerts');
        const alerts = expense.alerts || [];
        box.hidden = alerts.length === 0;
        document.getElementById('detail-alerts-list').replaceChildren(
            ...alerts.map((alert) => element('li', { text: alert })),
        );
    }

    function renderFields(expense) {
        const editable = canEdit();
        const fields = expense.fields;
        fieldInputs.number.value = fields.number;
        fieldInputs.issue_date.value = fields.issue_date;
        fieldInputs.cnpj.value = fields.cnpj_display;
        fieldInputs.total.value = toInputDecimal(fields.total);
        fieldInputs.access_key.value = fields.access_key;
        if (fields.expense_type_id && !typeSelect.querySelector(`option[value="${fields.expense_type_id}"]`)) {
            typeSelect.append(element('option', { value: fields.expense_type_id, text: expense.expense_type }));
        }
        typeSelect.value = fields.expense_type_id || '';
        Object.values(fieldInputs).forEach((input) => {
            input.disabled = !editable;
            input.classList.remove('invalid');
        });
        document.getElementById('add-item').hidden = !editable;
        state.items = expense.items.map((item) => ({
            ...item,
            quantity: formatQuantity(item.quantity),
            amount: toInputDecimal(item.amount),
        }));
        renderItems();
    }

    function renderActions(expense) {
        const actions = document.getElementById('detail-actions');
        actions.hidden = !expense.can.act;
        if (!expense.can.act) return;
        const control = expense.status === 'C' || expense.status === 'E';
        document.getElementById('correction-button').textContent = control
            ? 'Pedir correção ao funcionário' : 'Pedir correção ao Controle';
        document.getElementById('approve-button').textContent = !control
            ? 'Aprovar' : (expense.explanation_required ? 'Explicar e aprovar' : 'Aprovar e enviar ao Financeiro');
        refreshApproveHint();
    }

    function renderTimeline(expense) {
        const list = document.getElementById('timeline');
        list.replaceChildren(...expense.timeline.map((event) => element('li', {}, [
            element('div', { className: 'event-title', text: event.action_display }),
            element('div', {
                className: 'event-meta',
                text: [event.created_at, event.author_name ? `${event.author_name} (${event.role_display})` : event.role_display, event.status_display].join(' · '),
            }),
            event.note ? element('p', { className: 'event-note', text: event.note }) : null,
            reviewer ? element('button', {
                type: 'button', className: 'button small', text: 'Ver a nota nesta etapa',
                onclick: () => showEventState(event.sequence),
            }) : null,
        ])));

        if (reviewer) {
            const options = expense.timeline.map((event) => element('option', {
                value: event.sequence, text: `${event.sequence}. ${event.action_display} (${event.created_at})`,
            }));
            const from = document.getElementById('audit-from');
            const to = document.getElementById('audit-to');
            from.replaceChildren(...options.map((option) => option.cloneNode(true)));
            to.replaceChildren(...options);
            const count = expense.timeline.length;
            from.value = String(Math.max(1, count - 1));
            to.value = String(count);
            document.getElementById('audit-result').hidden = true;
        }
    }

    function renderResubmit(expense) {
        const box = document.getElementById('resubmit-box');
        box.hidden = !expense.can.resubmit;
    }

    function renderDetail(expense) {
        state.expense = expense;
        state.history = null;
        document.getElementById('detail-title').textContent = `Nota #${expense.id}`;
        const badge = document.getElementById('detail-status');
        badge.className = `status-badge status-${expense.status}`;
        badge.textContent = expense.status_display;
        renderNotice(expense);
        renderPhotos(expense);
        renderMeta(expense);
        renderAlerts(expense);
        renderFields(expense);
        renderActions(expense);
        renderTimeline(expense);
        renderResubmit(expense);
    }

    async function loadDetail(id) {
        try {
            const data = await api(urlFor('expenseUrl', id));
            showView('detail-view');
            renderDetail(data.expense);
            if (state.flash) showSuccess(state.flash);
        } catch (error) {
            showView('list-view');
            loadList();
            showError(error.message);
        } finally {
            state.flash = null;
        }
    }

    function markInvalid(errors) {
        for (const name of Object.keys(errors || {})) {
            if (fieldInputs[name]) fieldInputs[name].classList.add('invalid');
        }
    }

    // ---------- Ações ----------

    const noteDialog = document.getElementById('note-dialog');
    const noteInput = document.getElementById('note-input');
    const noteError = document.getElementById('note-error');

    function askNote({ title, text, label, button, required, danger }) {
        document.getElementById('note-title').textContent = title;
        document.getElementById('note-text').textContent = text;
        document.getElementById('note-label').textContent = label;
        const confirmButton = document.getElementById('note-confirm');
        confirmButton.textContent = button;
        confirmButton.classList.toggle('danger', Boolean(danger));
        noteInput.value = '';
        noteError.hidden = true;

        return new Promise((resolve) => {
            const finish = (value) => {
                noteDialog.close();
                document.getElementById('note-form').onsubmit = null;
                document.getElementById('note-cancel').onclick = null;
                noteDialog.oncancel = null;
                resolve(value);
            };
            document.getElementById('note-form').onsubmit = (event) => {
                event.preventDefault();
                const note = noteInput.value.trim();
                if (required && !note) {
                    noteError.textContent = 'A observação é obrigatória.';
                    noteError.hidden = false;
                    noteInput.focus();
                    return;
                }
                finish(note);
            };
            document.getElementById('note-cancel').onclick = () => finish(null);
            noteDialog.oncancel = (event) => {
                event.preventDefault();
                finish(null);
            };
            noteDialog.showModal();
            noteInput.focus();
        });
    }

    function actionDialog(action, expense) {
        const control = expense.status === 'C' || expense.status === 'E';
        if (action === 'reject') {
            return {
                title: `Rejeitar a nota #${expense.id}?`,
                text: 'A nota fica encerrada de vez, sem reenvio. O funcionário recebe o motivo por e-mail.',
                label: 'Motivo da rejeição (obrigatório)',
                button: 'Rejeitar',
                required: true,
                danger: true,
            };
        }
        if (action === 'request_correction') {
            return control ? {
                title: 'Pedir correção ao funcionário?',
                text: 'A nota volta ao funcionário para ele enviar novas fotos. Os dados que você editou ficam guardados.',
                label: 'O que o funcionário precisa corrigir (obrigatório)',
                button: 'Pedir correção',
                required: true,
            } : {
                title: 'Pedir correção ao Controle?',
                text: 'A nota volta ao Controle, que responde com uma explicação ou pede a correção ao funcionário.',
                label: 'O que o Controle precisa explicar ou corrigir (obrigatório)',
                button: 'Pedir correção',
                required: true,
            };
        }
        if (!control) {
            return {
                title: `Aprovar a nota #${expense.id}?`,
                text: `Valor reembolsado: ${expense.reimbursed_total}. A aprovação encerra a nota e dispara o lançamento no RM.`,
                label: 'Observação (opcional)',
                button: 'Aprovar',
                required: false,
            };
        }
        return expense.explanation_required ? {
            title: 'Explicar e aprovar?',
            text: 'A nota volta ao Financeiro com a sua explicação.',
            label: 'Explicação ao Financeiro (obrigatória)',
            button: 'Enviar ao Financeiro',
            required: true,
        } : {
            title: 'Aprovar e enviar ao Financeiro?',
            text: `Valor reembolsado: ${formatMoney(totals().reimbursed)}.`,
            label: 'Observação (opcional)',
            button: 'Aprovar',
            required: false,
        };
    }

    document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', async () => {
        const expense = state.expense;
        if (!expense) return;
        clearMessages();
        const action = button.dataset.action;
        const note = await askNote(actionDialog(action, expense));
        if (note === null) return;

        const payload = { action, note, version: expense.version };
        if (canEdit()) payload.data = formData();
        const buttons = document.querySelectorAll('[data-action]');
        buttons.forEach((item) => { item.disabled = true; });
        try {
            const data = await postJson(urlFor('actionUrl', expense.id), payload);
            renderDetail(data.expense);
            showSuccess(`Nota #${expense.id}: ${data.expense.status_display}.`);
        } catch (error) {
            showError(error.message);
            markInvalid(error.data && error.data.errors);
        } finally {
            buttons.forEach((item) => { item.disabled = false; });
            refreshApproveHint();
        }
    }));

    // ---------- Reenvio ----------

    if (access.employee) {
        const resendButton = document.getElementById('resubmit-send');
        const resendNote = document.getElementById('resubmit-note');
        const picker = photoPicker('resubmit', (count) => { resendButton.disabled = count === 0; });

        resendButton.addEventListener('click', async () => {
            const expense = state.expense;
            clearMessages();
            resendButton.disabled = true;
            try {
                const data = await api(urlFor('photosUrl', expense.id), {
                    method: 'POST',
                    body: photosForm(picker.files(), resendNote.value),
                });
                picker.clear();
                resendNote.value = '';
                renderDetail(data.expense);
                showSuccess('Fotos reenviadas. A nota volta para a conferência do Controle.');
            } catch (error) {
                showError(error.message);
                resendButton.disabled = picker.files().length === 0;
            }
        });
    }

    // ---------- Auditoria ----------

    const auditResult = document.getElementById('audit-result');

    function table(headers, rows) {
        return element('table', {}, [
            element('thead', {}, [element('tr', {}, headers.map((header) => element('th', { text: header })))]),
            element('tbody', {}, rows.map((row) => element('tr', {}, row.map((cell) => element('td', {}, [cell]))))),
        ]);
    }

    function renderState(event) {
        const snapshot = event.state;
        const fields = snapshot.fields;
        const reading = snapshot.ai_reading || {};
        const money = (value) => (value === '' || value === null) ? '-' : formatMoney(toCents(value));
        const date = (value) => value ? value.split('-').reverse().join('/') : '-';
        auditResult.replaceChildren(
            element('h4', { text: `Etapa ${event.sequence}: ${event.action_display}` }),
            element('p', {
                text: `${event.created_at} · ${event.author_name} (${event.role_display}) · ${event.status_before_display ? `${event.status_before_display} → ` : ''}${event.status_display}`,
            }),
            event.note ? element('p', { text: `Observação: ${event.note}` }) : null,
            element('h4', { text: 'Dados da nota' }),
            table(['Campo', 'Valor'], [
                ['Número da nota', fields.number || '-'],
                ['Data', date(fields.issue_date)],
                ['CNPJ do emitente', fields.cnpj || '-'],
                ['Valor total', money(fields.total)],
                ['Tipo', fields.expense_type || '-'],
                ['Chave de acesso', fields.access_key || '-'],
                ['Valor reembolsado', money(snapshot.reimbursed_total)],
                ['Observação do funcionário', snapshot.employee_note || '-'],
            ]),
            element('h4', { text: 'Itens' }),
            snapshot.items.length ? table(['Descrição', 'Qtd.', 'Valor', 'Não reembolsável', 'IA'], snapshot.items.map((item) => [
                item.description, formatQuantity(item.quantity), money(item.amount), item.non_reimbursable ? 'Sim' : 'Não',
                item.ai_group || '-',
            ])) : element('p', { className: 'muted', text: 'Nenhum item.' }),
            element('h4', { text: 'Fotos' }),
            element('div', { className: 'audit-photos' }, snapshot.photos.map((photo) => element('a', {
                href: photo.url, target: '_blank', rel: 'noopener', title: `Foto ${photo.position + 1}, envio ${photo.round}`,
            }, [element('img', { src: photo.url, alt: `Foto ${photo.position + 1}, envio ${photo.round}`, loading: 'lazy' })]))),
            element('h4', { text: 'Alertas da IA' }),
            snapshot.ai_alerts.length
                ? element('ul', {}, snapshot.ai_alerts.map((alert) => element('li', { text: alert })))
                : element('p', { className: 'muted', text: 'Nenhum alerta.' }),
            element('details', {}, [
                element('summary', { text: `Leitura da IA (${reading.status || 'sem leitura'}${reading.model ? `, ${reading.model}` : ''})` }),
                element('pre', { text: JSON.stringify(reading, null, 2) }),
            ]),
        );
        auditResult.hidden = false;
        auditResult.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    async function loadHistory() {
        if (!state.history) {
            const data = await api(urlFor('historyUrl', state.expense.id));
            state.history = data.events;
        }
        return state.history;
    }

    async function showEventState(sequence) {
        try {
            const events = await loadHistory();
            const event = events.find((item) => item.sequence === sequence);
            if (event) renderState(event);
        } catch (error) {
            showError(error.message);
        }
    }

    function changeLine(change) {
        return element('li', {}, [
            `${change.label}: `,
            element('span', { className: 'before', text: change.before || '(vazio)' }),
            ' → ',
            element('span', { className: 'after', text: change.after || '(vazio)' }),
        ]);
    }

    function renderComparison(data) {
        const changes = data.changes;
        const sections = [];
        if (changes.status) {
            sections.push(element('h4', { text: 'Situação' }), element('ul', {}, [changeLine({ label: 'Situação', ...changes.status })]));
        }
        if (changes.fields.length) {
            sections.push(element('h4', { text: 'Dados da nota' }), element('ul', {}, changes.fields.map(changeLine)));
        }
        const items = changes.items;
        if (items.added.length || items.removed.length || items.changed.length) {
            sections.push(element('h4', { text: 'Itens' }), element('ul', {}, [
                ...items.added.map((item) => element('li', { className: 'after', text: `Incluído: ${item.description} (${item.quantity} × ${item.amount}${item.non_reimbursable ? ', não reembolsável' : ''})` })),
                ...items.removed.map((item) => element('li', { className: 'before', text: `Removido: ${item.description} (${item.amount})` })),
                ...items.changed.map((item) => element('li', {}, [
                    `Alterado: ${item.description}`,
                    element('ul', {}, item.changes.map(changeLine)),
                ])),
            ]));
        }
        if (changes.reimbursed_total) {
            sections.push(element('h4', { text: 'Valor reembolsado' }), element('ul', {}, [changeLine(changes.reimbursed_total)]));
        }
        if (changes.photos) {
            const fromPhotos = new Map(data.from.state.photos.map((photo) => [photo.id, photo]));
            const toPhotos = new Map(data.to.state.photos.map((photo) => [photo.id, photo]));
            const thumbs = (ids, photos) => element('div', { className: 'audit-photos' }, ids.map((id) => element('a', {
                href: photos.get(id).url, target: '_blank', rel: 'noopener',
            }, [element('img', { src: photos.get(id).url, alt: 'Foto', loading: 'lazy' })])));
            sections.push(
                element('h4', { text: 'Fotos substituídas' }),
                element('p', { className: 'muted', text: 'Antes:' }), thumbs(changes.photos.removed, fromPhotos),
                element('p', { className: 'muted', text: 'Depois:' }), thumbs(changes.photos.added, toPhotos),
            );
        }
        if (changes.alerts) {
            sections.push(element('h4', { text: 'Alertas da IA' }), element('p', {
                text: `${changes.alerts.before.length} antes, ${changes.alerts.after.length} depois.`,
            }));
        }
        auditResult.replaceChildren(
            element('h4', { text: `Da etapa ${data.from.sequence} (${data.from.action_display}) para a ${data.to.sequence} (${data.to.action_display})` }),
            ...(sections.length ? sections : [element('p', { className: 'muted', text: 'Nada mudou entre as duas etapas.' })]),
        );
        auditResult.hidden = false;
    }

    const atButton = document.getElementById('audit-at-button');
    if (atButton) {
        atButton.addEventListener('click', async () => {
            const at = document.getElementById('audit-at').value;
            if (!at) {
                showError('Informe a data e a hora.');
                return;
            }
            try {
                const data = await api(`${urlFor('stateUrl', state.expense.id)}?${new URLSearchParams({ at })}`);
                renderState(data.event);
            } catch (error) {
                showError(error.message);
            }
        });

        document.getElementById('audit-compare-button').addEventListener('click', async () => {
            const params = new URLSearchParams({
                from: document.getElementById('audit-from').value,
                to: document.getElementById('audit-to').value,
            });
            try {
                renderComparison(await api(`${urlFor('compareUrl', state.expense.id)}?${params}`));
            } catch (error) {
                showError(error.message);
            }
        });
    }

    form.addEventListener('submit', (event) => event.preventDefault());

    // ---------- Início ----------

    if (openExpense && !window.location.hash) {
        // O link do e-mail e do card da home (?nota=12) abre direto a nota
        history.replaceState(null, '', `${window.location.pathname}#nota-${openExpense}`);
    }
    route();
})();
